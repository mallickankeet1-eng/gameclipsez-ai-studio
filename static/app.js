const $=id=>document.getElementById(id), btn=$("go");
let active=false;
btn.addEventListener("click",async()=>{
 if(active)return;
 const file=$("video").files[0], url=$("url").value.trim();
 if(!file&&!url){$("status").textContent="Choose a video file or paste a YouTube link first.";return}
 if(file&&file.size>150*1024*1024){$("status").textContent="This file is over the 150 MB free-server limit. Compress it or choose a shorter video.";return}
 active=true;btn.disabled=true;$("results").innerHTML="";$("status").textContent=file?"Uploading video…":"Connecting to YouTube…";
 try{
  let r;
  if(file){
   const form=new FormData();form.append("video",file);
   ["mode","count","length","aspect","framing","captions","caption_style"].forEach(id=>form.append(id,$(id).value));
   r=await fetch("/upload",{method:"POST",body:form});
  }else{
   r=await fetch("/create",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url,mode:$("mode").value,count:$("count").value,length:$("length").value,aspect:$("aspect").value,framing:$("framing").value,captions:$("captions").value,caption_style:$("caption_style").value})});
  }
  const d=await safeJson(r);
  if(!r.ok)throw Error(d.error||"Could not start the job (HTTP "+r.status+").");
  const id=d.job_id;
  const poll=async()=>{
   const response=await fetch("/status/"+id,{cache:"no-store"});
   const s=await safeJson(response);
   if(!response.ok)throw Error(s.message||"The job status was lost. Please start again.");
   $("status").textContent=s.message||s.status;
   if(s.status==="done"){render(s);return}
   if(s.status==="error")throw Error(s.message||"Processing failed.");
   setTimeout(()=>poll().catch(fail),3000);
  };
  await poll();
 }catch(e){fail(e)}
});
async function safeJson(response){
 const text=await response.text();
 try{return JSON.parse(text)}catch(_){throw Error("The server returned an unexpected response (HTTP "+response.status+"). Try a smaller MP4 or refresh the page.")}
}
function fail(e){active=false;btn.disabled=false;$("status").textContent="Error: "+e.message}
function render(s){
 active=false;btn.disabled=false;$("status").textContent="Your clips are ready. Download the ZIP below.";
 let h='<a class="download" href="'+s.download+'">⬇ DOWNLOAD ALL CLIPS (ZIP)</a>';
 (s.ideas||[]).forEach((x,i)=>{h+='<div class="clip"><h4>CLIP '+(i+1)+' · '+x.start+'s – '+x.end+'s</h4><p><b>Title ideas</b><br>'+x.titles.join("<br>")+'</p><p><b>Caption</b><br>'+x.caption+'</p></div>'});
 $("results").innerHTML='<div class="result">'+h+'</div>';
}
