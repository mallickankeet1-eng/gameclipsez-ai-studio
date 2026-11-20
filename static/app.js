const $=id=>document.getElementById(id), btn=$("go");
btn.addEventListener("click",async()=>{
 const url=$("url").value.trim(); if(!url){$("status").textContent="Paste a YouTube link first.";return}
 btn.disabled=true;$("results").innerHTML="";$("status").textContent="Starting video analysis…";
 try{
  const r=await fetch("/create",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url,mode:$("mode").value,count:$("count").value,length:$("length").value})});
  const d=await r.json();if(!r.ok)throw Error(d.error||"Could not start job");
  const id=d.job_id;
  const poll=async()=>{const s=await (await fetch("/status/"+id)).json();$("status").textContent=s.message||s.status;
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
