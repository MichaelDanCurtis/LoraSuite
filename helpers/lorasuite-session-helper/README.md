# LoraSuite Session Helper

Local unpacked browser extension for scanning the active Instagram post or reel into LoraSuite.

## Install

1. Open Chrome or a Chromium browser.
2. Navigate to `chrome://extensions`.
3. Enable **Developer mode**.
4. Click **Load unpacked**.
5. Select `helpers/lorasuite-session-helper`.

## Use

1. Start the LoraSuite engine at `http://127.0.0.1:8765`.
2. Open an Instagram post or reel in the same browser.
3. Click the **LoraSuite Session Helper** extension.
4. Click **Scan Current Instagram Page**.
5. Open LoraSuite -> **Data Ingress** -> **Instagram Source**.
6. Click **Load Helper Candidates**.
7. Review candidates in Tile, List, or Gallery mode, then confirm selected items.

The helper reads page metadata and poster image references from the active tab. It does not read, copy, send, or store browser cookies, authorization headers, CSRF tokens, or session fields.
