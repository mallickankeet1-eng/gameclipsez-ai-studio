import os, re, json, uuid, threading, subprocess, zipfile
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file, abort
import yt_dlp, imageio_ffmpeg

app = Flask(__name__)
BASE = Path(__file__).resolve().parent
WORK = BASE / "jobs"
WORK.mkdir(exist_ok=True)
JOBS = {}
LOCK = threading.Lock()
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

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

def render_job(job_id, url, mode, count, length):
    folder=WORK/job_id
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with LOCK: JOBS[job_id]["status"]="downloading"; JOBS[job_id]["message"]="Getting video and subtitles…"
        opts={"format":"bestvideo[height<=1080]+bestaudio/best[height<=1080]","merge_output_format":"mp4",
              "outtmpl":str(folder/"source.%(ext)s"),"writesubtitles":True,"writeautomaticsub":True,
              "subtitleslangs":["en","hi"],"subtitlesformat":"vtt/best","noplaylist":True}
        with yt_dlp.YoutubeDL(opts) as y: info=y.extract_info(url,download=True)
        vids=[p for p in folder.glob("source.*") if p.suffix.lower() in [".mp4",".mkv",".webm",".mov"]]
        if not vids: raise Exception("Could not download video. Try a public video or upload a local file in a future version.")
        video=vids[0]; duration=float(info.get("duration") or 0)
        if not duration: raise Exception("Could not read video duration.")
        vtts=list(folder.glob("*.vtt"))
        cues=parse_vtt(vtts[0]) if vtts else []
        candidates=[]
        if cues:
            for start in range(0,max(1,int(duration-length)+1),max(4,length//3)):
                end=min(duration,start+length)
                text=' '.join(x[2] for x in cues if x[0]<end and x[1]>start)
                if len(text.split())>=5: candidates.append((score(text,mode),start,end,text))
            candidates.sort(reverse=True)
            chosen=[]
            for c in candidates:
                if all(abs(c[1]-x[1])>=length*.75 for x in chosen):
                    chosen.append(c)
                if len(chosen)>=count: break
            chosen.sort(key=lambda x:x[1])
        else:
            L=min(length,max(15,int(duration/max(count,1))))
            chosen=[(0,i*duration/count,min(duration,i*duration/count+L),"") for i in range(count) if i*duration/count<duration]
        if not chosen: raise Exception("No suitable clip sections found.")
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
            words=(transcript or info.get("title","Video")).split()
            hook=" ".join(words[:9]).strip(" .,!?:;")
            mode_tag=re.sub(r'\W+','',mode.lower())
            ideas.append({"clip":out.name,"start":round(start),"end":round(end),
                "titles":[f"{hook} 😱", "You NEED to see this! 🔥", "Wait for it… 👀"],
                "caption":f"{hook} #shorts #reels #{mode_tag}"})
        (folder/"POSTING_IDEAS.json").write_text(json.dumps(ideas,ensure_ascii=False,indent=2),encoding="utf-8")
        zipname=folder/"Gameclipsez_Clips.zip"
        with zipfile.ZipFile(zipname,"w",zipfile.ZIP_DEFLATED) as z:
            for p in folder.glob("short_*.mp4"): z.write(p,p.name)
            z.write(folder/"POSTING_IDEAS.json","POSTING_IDEAS.json")
        with LOCK:
            JOBS[job_id].update(status="done",message="Your clips are ready!",ideas=ideas,download=f"/download/{job_id}")
    except Exception as e:
        with LOCK: JOBS[job_id].update(status="error",message=str(e))

@app.get("/")
def home():
    return render_template("index.html")

@app.post("/create")
def create():
    data=request.get_json(force=True)
    url=(data.get("url") or "").strip()
    if not re.match(r"https?://(www\.)?(youtube\.com|youtu\.be)/",url):
        return jsonify(error="Please paste a valid public YouTube URL."),400
    mode=data.get("mode","Gaming")
    try:
        count=max(1,min(10,int(data.get("count",5))))
        length=max(15,min(90,int(data.get("length",35))))
    except Exception: return jsonify(error="Clip count or length is invalid."),400
    jid=uuid.uuid4().hex[:12]
    with LOCK: JOBS[jid]={"status":"queued","message":"Starting…","ideas":[]}
    threading.Thread(target=render_job,args=(jid,url,mode,count,length),daemon=True).start()
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
