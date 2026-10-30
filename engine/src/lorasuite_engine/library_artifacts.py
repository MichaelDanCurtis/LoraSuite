"""Reviewed metadata and local preview bundles for LoRA Manager."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from PIL import Image, ImageOps, PngImagePlugin
from pydantic import BaseModel, Field
from lorasuite_engine.storage import atomic_write_json, json_file_lock


class ArtifactLibraryOptions(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    base_model: str | None = Field(default=None, max_length=200)
    trigger_words: list[str] | None = Field(default=None, max_length=32)
    tags: list[str] = Field(default_factory=list, max_length=50)
    description: str = Field(default='', max_length=10000)
    preview_paths: list[str] = Field(default_factory=list, max_length=12)
    replace_metadata: bool = False


def prepare_previews(paths: list[str]):
    result = []
    for value in paths:
        source = Path(value).expanduser().resolve(strict=True)
        if source.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'} or source.stat().st_size > 25 * 1024**2:
            raise ValueError('Choose PNG, JPEG or WebP previews under 25 MiB')
        with Image.open(source) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError('Preview exceeds 40 megapixels')
            pnginfo = PngImagePlugin.PngInfo()
            for key in ('parameters', 'prompt', 'workflow'):
                value = image.info.get(key)
                if isinstance(value, str) and len(value) <= 100_000:
                    pnginfo.add_text(key, value)
            rendered = ImageOps.exif_transpose(image).convert('RGB')
            rendered.thumbnail((2048, 2048))
            buffer = io.BytesIO()
            rendered.save(buffer, format='PNG', pnginfo=pnginfo)
        raw = buffer.getvalue()
        digest = hashlib.sha256(raw).hexdigest()
        if not any(item[0] == digest for item in result):
            result.append((digest, raw))
    return result


def finish_export(bridge, receipt, options, previews, previous, *, preserve_metadata=False):
    target = Path(receipt['path'])
    sidecar = target.with_suffix('.metadata.json')
    import json
    with json_file_lock(sidecar):
        data = json.loads(sidecar.read_text())
        if data.get('metadata_source') != 'lorasuite':
            raise ValueError('Existing metadata belongs to LoRA Manager; edit it there')
        if preserve_metadata and not options.replace_metadata:
            # Never silently replace the user's edits or switch their chosen cover.
            receipt['metadata_preserved'] = True
        else:
            fields = {'tags': [tag[:200] for tag in options.tags], 'notes': options.description,
                      'modelDescription': options.description}
            if options.title is not None:
                fields['model_name'] = options.title.strip() or data['model_name']
            if options.base_model is not None:
                fields['base_model'] = options.base_model.strip() or 'Unknown'
            if options.trigger_words is not None:
                fields['trainedWords'] = [word.strip()[:300] for word in options.trigger_words if word.strip()]
            data.update(fields)
            # Pinned LM's trigger-word formatter reads civitai.trainedWords even for
            # local models. Store words there without inventing Civitai model IDs.
            data.setdefault('civitai', {})['trainedWords'] = data.get('trainedWords', [])
        preview_dir = target.parent / (target.stem + '.previews')
        staged = []
        for digest, raw in previews:
            preview_dir.mkdir(exist_ok=True)
            path = preview_dir / (digest + '.png')
            if not path.exists():
                partial = path.with_suffix('.partial')
                try:
                    partial.write_bytes(raw)
                    partial.replace(path)
                finally:
                    partial.unlink(missing_ok=True)
            elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError('A staged preview has changed; review the library copy')
            staged.append(str(path))
        if staged and (not preserve_metadata or options.replace_metadata):
            data['preview_url'] = staged[0]
        atomic_write_json(sidecar, data)
    receipt['preview_paths'] = list(dict.fromkeys([*(previous or {}).get('preview_paths', []), *staged]))
    receipt['gallery_imported_paths'] = list((previous or {}).get('gallery_imported_paths', []))
    receipt['manager_synced'] = False
    receipt['sync_issue'] = ''
    gallery_configured_now = False
    try:
        roots = bridge.manager(roots=True).get('roots', [])
        if not any(target.resolve().is_relative_to(Path(root).resolve()) for root in roots):
            raise ValueError('LoRA Manager is using another library. Select the LoraSuite library, then send again.')
        if receipt['preview_paths']:
            settings = bridge.manager_api('/settings').get('settings')
            if not isinstance(settings, dict):
                raise ValueError('LoRA Manager settings response is unavailable; review its connection')
            if not settings.get('example_images_path'):
                gallery = bridge.root / 'model_library' / 'example_images'
                gallery.mkdir(parents=True, exist_ok=True)
                bridge.manager_api('/settings', {'example_images_path': str(gallery)})
                gallery_configured_now = True
        scan = bridge.manager_api('/loras/scan')
        if scan.get('status') != 'success':
            raise ValueError('LoRA Manager scan did not complete')
        # LM's fast scan does not reload changed sidecars for known files. Its
        # save API with no updates reloads current disk metadata into the cache.
        bridge.manager_api('/loras/save-metadata', {'file_path': str(target)})
        journal_path = target.with_suffix('.gallery-imports.json')
        with json_file_lock(journal_path):
            imports = json.loads(journal_path.read_text()) if journal_path.exists() else {}
            for path in receipt['preview_paths']:
                if path in receipt['gallery_imported_paths'] or imports.get(path) == 'imported':
                    if path not in receipt['gallery_imported_paths']:
                        receipt['gallery_imported_paths'].append(path)
                    continue
                if path in imports:
                    raise ValueError('An image import has an uncertain result. Review the gallery in LoRA Manager; use its Add images control for any missing staged previews.')
                # Persist intent BEFORE requesting a non-idempotent upstream
                # import. Lost replies and crashes must not duplicate images.
                imports[path] = 'needs_review'
                atomic_write_json(journal_path, imports)
                result = bridge.manager_api('/import-example-images', {'model_hash': receipt['sha256'], 'file_paths': [path]})
                if result.get('errors') or len(result.get('files', [])) != 1:
                    raise ValueError('Example image import was incomplete. Review the gallery in LoRA Manager.')
                imports[path] = 'imported'
                atomic_write_json(journal_path, imports)
                receipt['gallery_imported_paths'].append(path)
        if gallery_configured_now:
            raise ValueError('Images copied and the gallery folder configured. Restart LoRA Manager when downloads are idle, then send again to verify the gallery.')
        if receipt['preview_paths']:
            gallery = bridge.manager_api('/example-image-files?model_hash=' + receipt['sha256'])
            if not gallery.get('files') or not all(bridge.manager_media_ready(item.get('path', '')) for item in gallery['files']):
                raise ValueError('Images copied, but LoRA Manager is not serving the gallery yet. Restart it when downloads are idle, then send again.')
        receipt['manager_synced'] = True
    except (OSError, ValueError) as error:
        receipt['sync_issue'] = str(error) if isinstance(error, ValueError) else 'LoRA Manager is unavailable. Start it and retry the handoff.'
    return receipt
