import os, re, json, uuid, threading, subprocess, zipfile, logging, traceback
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, jsonify, send_file, abort
import yt_dlp, imageio_ffmpeg

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gameclipsez")
app = Flask(__name__)
# Render's free instance has only 512 MB RAM; keep uploads modest.
app.config["MAX_CONTENT_LENGTH"] = 150 * 1024 * 1024
BASE = Path(__file__).resolve().parent
WORK = Path(os.environ.get("GAMECLIPSEZ_WORKDIR", "/tmp/gameclipsez-jobs"))
WORK.mkdir(parents=True, exist_ok=True)
JOBS = {}
LOCK = threading.Lock()
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
ALLOWED_VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

@app.errorhandler(413)
def too_large(_):
    return jsonify(error="This video is over the 150 MB limit for the free server. Compress it or upload a shorter video."), 413

@app.errorhandler(500)
def server_error(_):
    log.exception("Unhandled server error")
    return jsonify(error="The server hit an unexpected error. Please refresh and try again with a smaller MP4."), 500

def parse_vtt(path):
    raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    cues=[]
    for block in re.split(r'\n\s*\n', raw):
        lines=block.strip().splitlines()
        timing=next((x for x in lines if '-->' in x), None)
        if not timing: continue
        try:
            a,b=[x.strip().split()[0] for x in timing.split('-->')]
            def sec(t):
                p=t.replace(',', '.').split(':')
                return sum(float(v)*60**(len(p)-i-1) for i,v in enumerate(p))
            txt=re.sub(r'<[^>]+>',' ',' '.join(lines[lines.index(timing)+1:]))
            txt=' '.join(txt.split())
            if txt: cues.append((sec(a),sec(b),txt))
        except Exception: pass
    return cues

def score(text, mode):
    t=text.lower()
    vocab={
      "Gaming":["insane","clutch","kill","headshot","win","enemy","crazy","1v","ace","fight","no way"],
      "Funny / Meme":["funny","fail","haha","lol","oops","bro","laugh","what"],
      "Education":["how","why","tip","learn","step","important","because","example"],
      "Podcast":["think","believe","story","experience","actually","opinion"],
      "Sports":["goal","score","match","team","player","champion","final"],
      "Reaction":["wow","what","seriously","shocked","react","unbelievable"],
      "Tutorial":["how","step","first","next","tutorial","guide","setup"],
      "Vlog":["today","morning","travel","went","visit","day","experience"],
      "Storytelling":["story","once","remember","happened","because","then","finally"],
      "Music":["song","music","beat","sing","dance","track","listen"],
      "Normal / Auto":["amazing","best","important","never","always","actually","really"]
    }.get(mode, [])
    return min(len(t.split()),50)*.1 + sum(2 for w in vocab if w in t) + len(re.findall(r'[.!?]',text))*1.5

def stamp(x):
    z=int(x); ms=int((x-z)*1000)
    return f"{z//3600:02}:{(z%3600)//60:02}:{z%60:02},{ms:03}"

def video_duration(path):
    result=subprocess.run([FFMPEG,"-hide_banner","-i",str(path)],capture_output=True,text=True,timeout=45)
    match=re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",result.stderr)
    if not match:
        raise Exception("We could not read this file as a video. Please try exporting it as MP4 (H.264 video).")
    h,m,s=match.groups()
    return int(h)*3600+int(m)*60+float(s)

def update_job(job_id, **values):
    with LOCK:
        if job_id in JOBS: JOBS[job_id].update(values)

def render_job(job_id, source, is_upload, mode, count, length, aspect, framing, captions, caption_style):
    folder=WORK/job_id
    folder.mkdir(parents=True, exist_ok=True)
    try:
        update_job(job_id,status="downloading",message="Preparing your video…")
        if is_upload:
            video=Path(source)
            if not video.exists() or video.stat().st_size == 0:
                raise Exception("The uploaded file was empty or could not be saved. Please upload it again.")
            duration=video_duration(video)
            title=video.stem
            subtitle_files=list(folder.glob("*.vtt"))
        else:
            update_job(job_id,message="Connecting to YouTube…")
            # Let current yt-dlp choose supported clients. Hard-coding clients can
            # make extraction less reliable as YouTube changes its player APIs.
            opts={
                "format":"best[height<=720][ext=mp4]/best[height<=720]/best",
                "outtmpl":str(folder/"source.%(ext)s"),
                "writesubtitles":True,"writeautomaticsub":True,
                "subtitleslangs":["en","hi"],"subtitlesformat":"vtt/best",
                "noplaylist":True,"js_runtimes":{"deno":{}},
                "retries":2,"fragment_retries":2,"socket_timeout":25,
                "verbose":False,"quiet":True,"no_warnings":False
            }
            try:
                with yt_dlp.YoutubeDL(opts) as y:
                    info=y.extract_info(source,download=True)
            except Exception as e:
                msg=str(e)
                log.exception("YouTube extraction failed for job %s",job_id)
                if any(x in msg.lower() for x in ["player response","not a bot","403","429","sign in","confirm your age"]):
                    raise Exception("YouTube refused this hosted server's download request. This is a YouTube/hosting restriction, not a clipper error. Download your own video using YouTube Studio, then use Upload Video. Public links may work again later.")
                raise Exception("Could not download this YouTube video: "+msg[-350:])
            vids=[p for p in folder.glob("source.*") if p.suffix.lower() in ALLOWED_VIDEO]
            if not vids:
                raise Exception("YouTube did not provide a downloadable video file. If this is your video, download it from YouTube Studio and upload the MP4 here.")
            video=vids[0]
            duration=float(info.get("duration") or video_duration(video))
            title=info.get("title","Video")
            subtitle_files=list(folder.glob("*.vtt"))
        if not duration or duration < 3:
            raise Exception("This video is too short or its duration could not be read.")
        cues=parse_vtt(subtitle_files[0]) if subtitle_files else []
        candidates=[]
        if cues:
            step=max(4,length//3)
            for start in range(0,max(1,int(duration-length)+1),step):
                end=min(duration,start+length)
                text=' '.join(x[2] for x in cues if x[0]<end and x[1]>start)
                if len(text.split())>=5: candidates.append((score(text,mode),start,end,text))
            candidates.sort(reverse=True)
            chosen=[]
            for c in candidates:
                if all(abs(c[1]-x[1])>=length*.75 for x in chosen): chosen.append(c)
                if len(chosen)>=count: break
            chosen.sort(key=lambda x:x[1])
        else:
            clip_len=min(length,max(10,int(duration/max(count,1))))
            chosen=[(0,i*duration/count,min(duration,i*duration/count+clip_len),"") for i in range(count) if i*duration/count<duration]
        if not chosen: raise Exception("No suitable clip sections found. Try a longer video or turn captions off.")
        ideas=[]
        for i,(_,start,end,transcript) in enumerate(chosen,1):
            update_job(job_id,status="rendering",message=f"Rendering clip {i} of {len(chosen)}…")
            srt=folder/f"captions_{i}.srt"
            if cues:
                lines=[]; n=1
                for a,b,txt in cues:
                    if b<=start or a>=end: continue
                    lines += [str(n),f"{stamp(max(0,a-start))} --> {stamp(min(end-start,b-start))}",txt,""]; n+=1
                srt.write_text("\n".join(lines),encoding="utf-8")
            out=folder/f"short_{i:02}.mp4"
            dimensions={"9:16":(720,1280),"1:1":(720,720),"16:9":(1280,720)}
            width,height=dimensions.get(aspect,(720,1280))
            if framing=="Fit whole video":
                vf=f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
            else:
                vf=f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
            if captions and srt.exists() and srt.stat().st_size:
                sp=str(srt).replace("\\","/")
                style="FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=3,Alignment=2,MarginV=70"
                if caption_style=="Bold / Large":
                    style="FontName=Arial,FontSize=24,Bold=1,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=4,Alignment=2,MarginV=80"
                vf+=f",subtitles='{sp}':force_style='{style}'"
            cmd=[FFMPEG,"-hide_banner","-y","-ss",str(start),"-i",str(video),"-t",str(end-start),
                 "-map","0:v:0","-map","0:a?","-vf",vf,"-c:v","libx264","-preset","ultrafast",
                 "-crf","26","-threads","1","-c:a","aac","-b:a","96k","-movflags","+faststart",
                 "-max_muxing_queue_size","1024",str(out)]
            res=subprocess.run(cmd,capture_output=True,text=True,timeout=600)
            if res.returncode or not out.exists() or out.stat().st_size==0:
                log.error("FFmpeg failed: %s",res.stderr[-3000:])
                raise Exception("Video conversion failed. Please try an MP4 (H.264) file, shorter clips, or a smaller video.")
            words=(transcript or title or "Video").split()
            hook=" ".join(words[:9]).strip(" .,!?:;")
            mode_tag=re.sub(r'\W+','',mode.lower())
            ideas.append({"clip":out.name,"start":round(start),"end":round(end),
                "titles":[f"{hook} 😱","You NEED to see this! 🔥","Wait for it… 👀"],
                "caption":f"{hook} #shorts #reels #{mode_tag}"})
        (folder/"POSTING_IDEAS.json").write_text(json.dumps(ideas,ensure_ascii=False,indent=2),encoding="utf-8")
        zipname=folder/"Gameclipsez_Clips.zip"
        with zipfile.ZipFile(zipname,"w",zipfile.ZIP_DEFLATED) as z:
            for p in folder.glob("short_*.mp4"): z.write(p,p.name)
            z.write(folder/"POSTING_IDEAS.json","POSTING_IDEAS.json")
        update_job(job_id,status="done",message="Your clips are ready!",ideas=ideas,download=f"/download/{job_id}")
    except Exception as e:
        log.exception("Job %s failed",job_id)
        update_job(job_id,status="error",message=str(e)[:700])

def start_job(source, is_upload, mode, count, length, aspect, framing, captions, caption_style):
    jid=uuid.uuid4().hex[:12]
    with LOCK: JOBS[jid]={"status":"queued","message":"Starting…","ideas":[]}
    threading.Thread(target=render_job,args=(jid,source,is_upload,mode,count,length,aspect,framing,captions,caption_style),daemon=True).start()
    return jid

def read_options(data):
    mode=data.get("mode","Gaming")
    aspect=data.get("aspect","9:16")
    framing=data.get("framing","Fill / Crop")
    captions=data.get("captions","on")=="on"
    caption_style=data.get("caption_style","Classic")
    if aspect not in ("9:16","1:1","16:9"): raise ValueError("Choose a valid output format.")
    count=max(1,min(7,int(data.get("count",5))))
    length=max(15,min(90,int(data.get("length",35))))
    return mode,count,length,aspect,framing,captions,caption_style

@app.get("/")
def home():
    return render_template("index.html")

@app.post("/create")
def create():
    data=request.get_json(silent=True) or {}
    url=(data.get("url") or "").strip()
    if not re.match(r"^https?://(www\.)?(youtube\.com|youtu\.be)/",url,re.I):
        return jsonify(error="Paste a valid YouTube video URL, or upload an MP4 video."),400
    try: opts=read_options(data)
    except (ValueError,TypeError): return jsonify(error="Clip count, clip length, or output format is invalid."),400
    return jsonify(job_id=start_job(url,False,*opts))

@app.post("/upload")
def upload():
    file=request.files.get("video")
    if not file or not file.filename: return jsonify(error="Choose a video file first."),400
    filename=secure_filename(file.filename)
    ext=Path(filename).suffix.lower()
    if ext not in ALLOWED_VIDEO: return jsonify(error="Use MP4, MOV, MKV, WEBM, AVI or M4V video."),400
    try: opts=read_options(request.form)
    except (ValueError,TypeError): return jsonify(error="Clip count, clip length, or output format is invalid."),400
    jid=uuid.uuid4().hex[:12]
    folder=WORK/jid
    folder.mkdir(parents=True,exist_ok=True)
    saved=folder/("uploaded_video"+ext)
    try: file.save(saved)
    except Exception:
        log.exception("Upload save failed")
        return jsonify(error="The upload could not be saved. Try a smaller MP4 (under 150 MB)."),500
    with LOCK: JOBS[jid]={"status":"queued","message":"Upload received. Starting…","ideas":[]}
    threading.Thread(target=render_job,args=(jid,str(saved),True,*opts),daemon=True).start()
    return jsonify(job_id=jid)

@app.get("/status/<jid>")
def status(jid):
    with LOCK: item=JOBS.get(jid)
    if not item: return jsonify(status="error",message="This job expired because the server restarted. Please start again."),404
    return jsonify(item)

@app.get("/download/<jid>")
def download(jid):
    p=WORK/jid/"Gameclipsez_Clips.zip"
    if not p.exists(): abort(404)
    return send_file(p,as_attachment=True,download_name="Gameclipsez_Clips.zip")

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=False)
