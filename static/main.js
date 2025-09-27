const elChat = document.getElementById("chat");
const elForm = document.getElementById("composer");
const elMsg  = document.getElementById("message");
const elSend = document.getElementById("send");
const elBadge = document.getElementById("csv-status");

let sending = false;

function esc(str){return (str??"").toString().replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}

function addMessage(role,text){
  const wrap=document.createElement("div"); wrap.className=`msg ${role}`;
  const avatar=document.createElement("div"); avatar.className="avatar"; avatar.textContent=role==="bot"?"🤖":"🙂";
  const bubble=document.createElement("div"); bubble.className="bubble"; bubble.innerHTML=esc(text);
  if(role==="bot") wrap.appendChild(avatar);
  wrap.appendChild(bubble);
  elChat.appendChild(wrap);
  elChat.scrollTop=elChat.scrollHeight;
}

function setSending(on){ sending=on; elSend.disabled=on; elSend.textContent=on?"Sending…":"Send"; }

async function fetchCsvStatus(){
  try{
    const r=await fetch("/debug/csv",{cache:"no-store"});
    if(!r.ok) throw new Error("status "+r.status);
    const j=await r.json();
    const en=j.en_count??0, es=j.es_count??0;
    elBadge.textContent=`Connected: EN ${en} · ES ${es}`;
    elBadge.className="badge ok";
  }catch(e){
    elBadge.textContent="No CSV connected";
    elBadge.className="badge warn";
  }
}

async function sendMessage(text){
  setSending(true);
  addMessage("user",text);
  try{
    const r=await fetch("/api/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({message:text})});
    const j=await r.json();
    if(j.error) throw new Error(j.error);
    addMessage("bot",j.reply);
  }catch(e){
    addMessage("bot","⚠️ Error: "+e.message);
  }finally{
    setSending(false);
  }
}

elForm.addEventListener("submit",(e)=>{
  e.preventDefault();
  const text=elMsg.value.trim();
  if(!text||sending) return;
  elMsg.value="";
  sendMessage(text);
});

elMsg.addEventListener("keydown",(e)=>{
  if(e.key==="Enter"&&!e.shiftKey){ e.preventDefault(); elForm.dispatchEvent(new Event("submit")); }
});

addMessage("bot","¡Hola! / Hi! Ask me anything about the school.\n(Respondo en Español o Inglés.)");
fetchCsvStatus();
