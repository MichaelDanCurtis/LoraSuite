import json
from pathlib import Path
import tempfile
import unittest

from h3_training_smoke import prepare, packed_to_device


class PrepareTest(unittest.TestCase):
    def test_mps_position_metadata_transfer(self):
        import torch
        if not torch.backends.mps.is_available():
            self.skipTest("MPS unavailable")
        packed = {"positions": torch.tensor([0.25, 1.5], dtype=torch.float64),
                  "indices": torch.tensor([1, 2], dtype=torch.int64), "count": 2}
        output = packed_to_device(packed, torch.device("mps"))
        self.assertEqual(output["positions"].dtype, torch.float32)
        self.assertEqual(output["indices"].dtype, torch.int64)
        self.assertEqual(output["positions"].cpu().tolist(), [0.25, 1.5])
        self.assertEqual(output["count"], 2)
        self.assertEqual(packed["positions"].dtype, torch.float64)

    def test_only_approved_distinct_sources_and_preserve_vault(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            media, items = [], {}
            for i in range(7):
                path = root / f"{i}.jpg"
                path.write_bytes(bytes([i]))
                media.append({"id": str(i), "raw_path": str(path)})
                items[str(i)] = {"status": "rejected" if i == 0 else "approved",
                                 "source_id": str(max(1, i - 1)), "training_media_item_id": str(i),
                                 "caption": "reviewed caption", "strongest_set_rank": i}
            snapshot = {"id": "test", "items": items, "intent": {"trigger_token": "subject"}}
            original = json.dumps({"snapshots": [snapshot]})
            (root / "dataset_snapshots.json").write_text(original)
            (root / "vault.json").write_text(json.dumps({"media_items": media}))
            prepare(root, root / "run", "test")
            train = json.loads((root / "run/train.json").read_text())
            held = json.loads((root / "run/heldout.json").read_text())
            self.assertEqual(len(train), 4)
            self.assertEqual(len(held), 1)
            self.assertEqual(len({row["source_id"] for row in train + held}), 5)
            self.assertNotIn("0", [row["media_id"] for row in train + held])
            self.assertEqual((root / "dataset_snapshots.json").read_text(), original)
            with self.assertRaises(FileExistsError):
                prepare(root, root / "run", "test")


if __name__ == "__main__":
    unittest.main()
