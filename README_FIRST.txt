GAMECLIPSEZ AI STUDIO — WEB APP
Created by Ankeet Mallick

This is a browser-based Flask web app, not a Windows desktop program.

DEPLOY ON RENDER:
1. Connect this GitHub repository to Render as a Web Service.
2. Build command: pip install -r requirements.txt
3. Start command: gunicorn app:app --bind 0.0.0.0:$PORT --timeout 900
4. Choose the free instance to test and deploy.

FEATURES / LIMITATIONS:
- YouTube URL -> download -> subtitle-based highlight scoring -> 9:16 MP4 clips.
- Modes: Gaming, Normal/Auto, Funny/Meme, Podcast, Education, Sports.
- Produces title/caption/hashtag ideas and ZIP download.
- This is an AI-assisted starter: it uses subtitles and keyword scoring, not a large generative AI model.
- It depends on accessible subtitles for smarter moment selection and burned-in captions.
- Without subtitles, it creates evenly spaced clips and has no captions.
- YouTube may block some videos (private, age restricted, members-only, region restricted).
- Free hosting has limited CPU/RAM/storage and may not reliably process long videos.
- Jobs and exports are temporary; a restart can erase them.
- It does NOT auto-post to YouTube or Instagram. Review and upload manually.
- Only use videos you own or have permission to download/edit.
