const $=id=>document.getElementById(id), btn=$("go");
btn.addEventListener("click",async()=>{
 const file=$("video").files[0], url=$("url").value.trim();
 if(!file&&!url){$("status").textContent="Choose a video file or paste a YouTube link first.";return}
 if(file&&file.size>500*1024*1024){$("status").textContent="This file is over the 500 MB limit. Choose a smaller video.";return}
 btn.disabled=true;$("results").innerHTML="";$("status").textContent=file?"Uploading video…":"Starting YouTube analysis…";
 try{
  let r;
  if(file){
   const form=new FormData();form.append("video",file);form.append("mode",$("mode").value);form.append("count",$("count").value);form.append("length",$("length").value);form.append("aspect",$("aspect").value);form.append("framing",$("framing").value);form.append("captions",$("captions").value);form.append("caption_style",$("caption_style").value);
   r=await fetch("/upload",{method:"POST",body:form});
  }else{
   r=await fetch("/create",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url,mode:$("mode").value,count:$("count").value,length:$("length").value,aspect:$("aspect").value,framing:$("framing").value,captions:$("captions").value,caption_style:$("caption_style").value})});
  }
  const d=await r.json();if(!r.ok)throw Error(d.error||"Could not start job");
  const id=d.job_id;
  const poll=async()=>{const response=await fetch("/status/"+id);const s=await response.json();$("status").textContent=s.message||s.status;
   if(s.status==="done"){btn.disabled=false;render(s);return}
   if(s.status==="error"){btn.disabled=false;$("status").textContent="Error: "+s.message;return}
   setTimeout(poll,2500)};
  poll();
 }catch(e){btn.disabled=false;$("status").textContent="Error: "+e.message}
});
function render(s){
 $("status").textContent="Your clips are ready. Download the ZIP below.";
 let h='<a class="download" href="'+s.download+'">⬇ DOWNLOAD ALL CLIPS (ZIP)</a>';
 (s.ideas||[]).forEach((x,i)=>{h+='<div class="clip"><h4>CLIP '+(i+1)+' · '+x.start+'s – '+x.end+'s</h4><p><b>Title ideas</b><br>'+x.titles.join("<br>")+'</p><p><b>Caption</b><br>'+x.caption+'</p></div>'});
 $("results").innerHTML='<div class="result">'+h+'</div>';
}