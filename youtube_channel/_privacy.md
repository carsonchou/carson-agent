# Privacy Policy — Carson Quant Studio

_Last updated: 2026-07-28_

**Carson Quant Studio** is an internal, single-operator tool used solely by its operator to manage the operator's **own** YouTube channel — [量化阿森 Carson Quant](https://www.youtube.com/@CarsonQuant) — via the YouTube API Services. It has no other users, no web frontend, and no user registration.

## Data we access

**1. The operator's own channel data.** Video uploads, titles, descriptions, custom thumbnails, captions, playlists, comments on our own videos, and our own channel analytics (views, watch time, traffic sources, subscriber counts). This is accessed through authenticated YouTube API access with OAuth consent granted by the channel owner's own account.

**2. Publicly available metadata about other creators' videos, for topic research.** Using the official YouTube Data API (`search.list` / `videos.list`), the tool retrieves public metadata — video titles, channel names, publication dates and public view counts — to decide which educational topics to cover next. Only public metadata is retrieved; the tool does **not** access any private data belonging to other users, and does **not** download, scrape, transcribe, or republish other creators' video content, audio, or captions.

## What we do **not** do

- **No scraping.** All data is obtained through official YouTube APIs. A previous pipeline component that downloaded third-party subtitles and audio was removed in July 2026 and is not in use.
- **No artificial engagement.** The tool never inflates views, likes, subscribers, or comments, and never engages with other channels on our behalf.
- **No selling or sharing.** No accessed data is sold, shared, transferred, or disclosed to any third party.
- **No access to other users' private data.** OAuth consent is obtained only from the channel owner's own account.

## Data storage & retention

All data is stored locally on the operator's own machine.

- Our own channel data is retained for as long as the channel is operated, and can be deleted at any time.
- **Stored copies of third-party public metadata are automatically purged after 30 calendar days**, in line with section III.E.4.d of the YouTube API Services Developer Policies. Research reports older than 30 days are deleted automatically by a scheduled job.

## YouTube API Services

This tool uses **YouTube API Services**. Its use adheres to the [YouTube Terms of Service](https://www.youtube.com/t/terms), the [YouTube API Services Developer Policies](https://developers.google.com/youtube/terms/developer-policies), and the [Google Privacy Policy](https://policies.google.com/privacy). API access can be reviewed or revoked at any time via [Google security settings](https://security.google.com/settings/security/permissions).

## Contact

moneycometomywallet@gmail.com
