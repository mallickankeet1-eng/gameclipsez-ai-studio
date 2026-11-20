import os, re, json, uuid, threading, subprocess, zipfile
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, jsonify, send_file, abort
import yt_dlp, imageio_ffmpeg

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB upload limit
BASE = Path(__file__).resolve().parent
WORK = BASE / "jobs"
WORK.mkdir(exist_ok=True)
JOBS = {}
LOCK = threading.Lock()
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
ALLOWED_VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

@app.errorhandler(413)
def too_large(_):
    return jsonify(error="That video is larger than the 500 MB upload limit. Try a shorter or smaller MP4."), 413

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
      "Normal / Auto":["amazing","best","important","never","always","actually","really"]
    }.get(mode, [])
    return min(len(t.split()),50)*.1 + sum(2 for w in vocab if w in t) + len(re.findall(r'[.!?]',text))*1.5

def stamp(x):
    z=int(x); ms=int((x-z)*1000)
    return f"{z//3600:02}:{(z%3600)//60:02}:{z%60:02},{ms:03}"

def video_duration(path):
    result=subprocess.run([FFMPEG,"-i",str(path)],capture_output=True,text=True)
    match=re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",result.stderr)
    if not match: raise Exception("Could not read this video's duration. Please try an MP4 file.")
    h,m,s=match.groups()
    return int(h)*3600+int(m)*60+float(s)

def render_job(job_id, source, is_upload, mode, count, length):
    folder=WORK/job_id
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with LOCK: JOBS[job_id]["status"]="downloading"; JOBS[job_id]["message"]="Preparing your video…"
        if is_upload:
            video=Path(source)
            duration=video_duration(video)
            title=video.stem
            subtitle_files=list(folder.glob("*.vtt"))
        else:
            opts={"format":"bestvideo[height<=1080]+bestaudio/best[height<=1080]","merge_output_format":"mp4",
                  "outtmpl":str(folder/"source.%(ext)s"),"writesubtitles":True,"writeautomaticsub":True,
                  "subtitleslangs":["en","hi"],"subtitlesformat":"vtt/best","noplaylist":True}
            with yt_dlp.YoutubeDL(opts) as y: info=y.extract_info(source,download=True)
            vids=[p for p in folder.glob("source.*") if p.suffix.lower() in ALLOWED_VIDEO]
            if not vids: raise Exception("YouTube could not provide this video. Download your own video and use the Upload Video option instead.")
            video=vids[0]; duration=float(info.get("duration") or 0); title=info.get("title","Video")
            subtitle_files=list(folder.glob("*.vtt"))
        if not duration: raise Exception("Could not read video duration.")
        cues=parse_vtt(subtitle_files[0]) if subtitle_files else []
        candidates=[]
        if cues:
            for start in range(0,max(1,int(duration-length)+1),max(4,length//3)):
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
            clip_len=min(length,max(15,int(duration/max(count,1))))
            chosen=[(0,i*duration/count,min(duration,i*duration/count+clip_len),"") for i in range(count) if i*duration/count<duration]
        if not chosen: raise Exception("No suitable clip sections found. Try a longer video.")
        ideas=[]
        for i,(_,start,end,transcript) in enumerate(chosen,1):
            with LOCK:
                JOBS[job_id]["status"]="rendering"
                JOBS[job_id]["message"]=f"Rendering clip {i} of {len(chosen)}…"
            srt=folder/f"captions_{i}.srt"
            if cues:
                lines=[]; n=1
                for a,b,txt in cues:
                    if b<=start or a>=end: continue
                    lines += [str(n),f"{stamp(max(0,a-start))} --> {stamp(min(end-start,b-start))}",txt,""]; n+=1
                srt.write_text("\n".join(lines),encoding="utf-8")
            out=folder/f"short_{i:02}.mp4"
            vf="scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
            if srt.exists() and srt.stat().st_size:
                sp=str(srt).replace("\\","/").replace(":","\\:")
                vf+=f",subtitles='{sp}':force_style='FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=3,Alignment=2,MarginV=100'"
            cmd=[FFMPEG,"-y","-ss",str(start),"-i",str(video),"-t",str(end-start),"-vf",vf,"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-b:a","128k","-movflags","+faststart",str(out)]
            res=subprocess.run(cmd,capture_output=True,text=True)
            if res.returncode: raise Exception("Video rendering failed: "+res.stderr[-500:])
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
        with LOCK: JOBS[job_id].update(status="done",message="Your clips are ready!",ideas=ideas,download=f"/download/{job_id}")
    except Exception as e:
        with LOCK: JOBS[job_id].update(status="error",message=str(e))

def start_job(source, is_upload, mode, count, length):
    jid=uuid.uuid4().hex[:12]
    with LOCK: JOBS[jid]={"status":"queued","message":"Starting…","ideas":[]}
    threading.Thread(target=render_job,args=(jid,source,is_upload,mode,count,length),daemon=True).start()
    return jid

@app.get("/")
def home():
    return render_template("index.html")

@app.post("/create")
def create():
    data=request.get_json(force=True)
    url=(data.get("url") or "").strip()
    if not re.match(r"https?://(www\.)?(youtube\.com|youtu\.be)/",url):
        return jsonify(error="Please paste a valid YouTube URL, or upload a video file instead."),400
    mode=data.get("mode","Gaming")
    try:
        count=max(1,min(10,int(data.get("count",5))))
        length=max(15,min(90,int(data.get("length",35))))
    except Exception: return jsonify(error="Clip count or length is invalid."),400
    return jsonify(job_id=start_job(url,False,mode,count,length))

@app.post("/upload")
def upload():
    file=request.files.get("video")
    if not file or not file.filename: return jsonify(error="Choose a video file first."),400
    filename=secure_filename(file.filename)
    ext=Path(filename).suffix.lower()
    if ext not in ALLOWED_VIDEO: return jsonify(error="Use MP4, MOV, MKV, WEBM, AVI or M4V video."),400
    mode=request.form.get("mode","Gaming")
    try:
        count=max(1,min(10,int(request.form.get("count",5))))
        length=max(15,min(90,int(request.form.get("length",35))))
    except Exception: return jsonify(error="Clip count or length is invalid."),400
    jid=uuid.uuid4().hex[:12]
    folder=WORK/jid
    folder.mkdir(parents=True,exist_ok=True)
    saved=folder/("uploaded_video"+ext)
    file.save(saved)
    with LOCK: JOBS[jid]={"status":"queued","message":"Upload received. Starting…","ideas":[]}
    threading.Thread(target=render_job,args=(jid,str(saved),True,mode,count,length),daemon=True).start()
    return jsonify(job_id=jid)

@app.get("/status/<jid>")
def status(jid):
    with LOCK: item=JOBS.get(jid)
    if not item: abort(404)
    return jsonify(item)

@app.get("/download/<jid>")
def download(jid):
    p=WORK/jid/"Gameclipsez_Clips.zip"
    if not p.exists(): abort(404)
    return send_file(p,as_attachment=True,download_name="Gameclipsez_Clips.zip")

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=False)
