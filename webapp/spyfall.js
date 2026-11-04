(function () {
  "use strict";
  var app = document.getElementById("app");
  var tg = window.Telegram && window.Telegram.WebApp;
  var code = "", state = null, me = null, timer = null, errorText = "";
  function user() {
    var u = tg && tg.initDataUnsafe && tg.initDataUnsafe.user;
    if (u) return {user_id:u.id, name:[u.first_name,u.last_name].filter(Boolean).join(" ") || u.username || "O'yinchi"};
    var id = Number(sessionStorage.getItem("rg_guest_id"));
    if (!id) { id = -Math.floor(Math.random()*900000000)-1; sessionStorage.setItem("rg_guest_id",String(id)); }
    return {user_id:id, name:sessionStorage.getItem("rg_guest_name") || "Mehmon"};
  }
  function req(path, body) {
    var headers = {"Content-Type":"application/json"};
    if (tg && tg.initData) headers["X-Telegram-Init-Data"] = tg.initData;
    return fetch(path, {method:body ? "POST" : "GET", headers:headers, body:body ? JSON.stringify(body) : undefined})
      .then(function(r){return r.json().then(function(d){if(!r.ok) throw new Error(d.detail || "Server xatosi"); return d;});});
  }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];}); }
  function toast(s) { var el=document.getElementById("toast"); if(el){el.textContent=s;el.classList.add("show");setTimeout(function(){el.classList.remove("show");},2400);} }
  function shell(content) {
    app.innerHTML = '<main class="fade mafia-shell"><div class="topbar"><button class="icon-btn" data-spy="home">←</button><div class="room-id"><span class="room-code">'+esc(code || "JOSUS")+'</span><span class="status-pill">🕶️ Josus</span></div></div>'+content+'<div class="footer">Revilend Games · Josus</div></main>';
  }
  function open() {
    code="";state=null;me=null;errorText="";
    if(timer) clearInterval(timer);
    if(tg && tg.BackButton) {tg.BackButton.show(); tg.BackButton.onClick(home);}
    shell('<section class="mafia-hero"><p class="mafia-kicker">REVILEND · SPYFALL</p><h1>🕶️ Josus</h1><p>3–10 kishi bilan o‘ynang. Xona yarating yoki do‘stingiz yuborgan kodni kiriting.</p></section><button class="btn primary block" data-spy="create">＋ Yangi xona yaratish</button><form id="spy-join" class="join-form" style="margin-top:12px"><input id="spy-code" maxlength="6" placeholder="SPY123" autocomplete="off"><button class="btn">Kirish</button></form><div class="notice" style="margin-top:14px">Har kimga maxfiy rol beriladi. Guruhda savol-javob qiling, so‘ng josusni topish uchun ovoz bering.</div>');
  }
  function home() {
    if(timer) clearInterval(timer); timer=null; code="";state=null;me=null;
    if(tg && tg.BackButton) tg.BackButton.hide();
    window.location.href=window.location.pathname;
  }
  function create() {
    req("/api/spy/create",user()).then(function(d){code=d.state.code;refresh();toast("Xona yaratildi: "+code);}).catch(function(e){toast(e.message);});
  }
  function join(c) {
    req("/api/spy/"+encodeURIComponent(c)+"/join",user()).then(function(){code=c;refresh();toast("Xonaga qo‘shildingiz");}).catch(function(e){toast(e.message);});
  }
  function refresh() {
    if(!code) return;
    req("/api/spy/"+encodeURIComponent(code)+"?user_id="+encodeURIComponent(user().user_id)).then(function(d){state=d.state;me=d.me;draw();}).catch(function(e){errorText=e.message;draw();});
  }
  function start() {
    req("/api/spy/"+encodeURIComponent(code)+"/start",user()).then(refresh).catch(function(e){toast(e.message);});
  }
  function vote(id) {
    req("/api/spy/"+encodeURIComponent(code)+"/vote",Object.assign(user(),{target_id:Number(id)})).then(function(d){state=d.state;me=d.me;draw();toast("Ovoz qabul qilindi");}).catch(function(e){toast(e.message);});
  }
  function draw() {
    if(!state) {shell('<div class="skeleton"></div><div class="skeleton"></div>');return;}
    if(errorText){shell('<section class="mafia-hero"><h2>Xona topilmadi</h2><p>'+esc(errorText)+'</p></section>');return;}
    var players=state.players||[], role="";
    if(me && me.role==="spy") role='<section class="mafia-reveal"><h2>🕶️ SIZ JOSUSSIZ!</h2><p class="muted tiny">Boshqalar joyni biladi. Savollarga ehtiyotkorlik bilan javob bering va yashirin joyni topishga harakat qiling.</p></section>';
    if(me && me.role==="player") role='<section class="mafia-reveal"><h2>📍 '+esc(me.location)+'</h2><p class="muted tiny">Bu joyni josusga bildirmang. Savollar orqali josusni aniqlang.</p></section>';
    var rows=players.map(function(p){var self=Number(p.user_id)===Number(user().user_id);return '<div class="player"><div class="avatar">'+(p.is_host?"👑":"👤")+'</div><div class="p-body"><div class="p-name">'+esc(p.name)+(self?' <span class="badge me">SIZ</span>':'')+'</div><div class="p-meta">'+(p.is_host?"Xona egasi · ":"")+(state.status==="FINISHED"?p.votes+" ovoz":"O‘yinda")+'</div></div>'+(state.status==="PLAYING"&&!self?'<button class="btn small" data-spy="vote" data-target="'+p.user_id+'">Josus deb ovoz</button>':'')+'</div>';}).join("");
    var controls="";
    if(state.status==="LOBBY") controls='<div class="notice">Xona kodi: <b>'+esc(code)+'</b>. Do‘stlaringizga yuboring. Kamida 3 kishi kerak.</div>'+(Number(state.host_id)===Number(user().user_id)?'<button class="btn primary block" data-spy="start" '+(players.length<3?'disabled':'')+'>▶️ O‘yinni boshlash</button>':'<p class="muted tiny">Xona egasi boshlashini kuting.</p>');
    if(state.status==="PLAYING") controls='<section class="vote-panel"><h2>🗳️ Josus kim?</h2><p class="muted">Guruhda savol-javobni davom ettiring. Har bir o‘yinchi shubhali odamga ovoz beradi.</p><p class="tiny muted">Ovozlar: '+state.votes_count+'/'+players.length+'</p></section>';
    if(state.status==="FINISHED") controls='<section class="mafia-reveal"><h2>'+(state.winner==="players"?"🎉 O‘yinchilar g‘alaba qildi!":"🕶️ Josus g‘alaba qildi!")+'</h2><p>Josus ID: '+esc(state.spy_id)+'</p><p class="muted tiny">Yangi o‘yin uchun bosh sahifaga qayting.</p></section>';
    shell('<section class="mafia-hero"><p class="mafia-kicker">SPYFALL · '+esc(state.status)+'</p><h1>'+(state.status==="LOBBY"?"O‘yinchilar yig‘ilmoqda":"Savol-javob vaqti!")+'</h1><p>'+(state.status==="LOBBY"?"Xona kodini do‘stlaringizga yuboring.":"Joyni sir saqlang va josusni toping.")+'</p></section>'+role+'<section class="panel"><h2>👥 O‘yinchilar ('+players.length+'/10)</h2><div class="players">'+rows+'</div></section>'+controls);
  }
  app.addEventListener("click",function(e){
    var b=e.target.closest("[data-act],[data-spy]");
    if(!b) return;
    var act=b.getAttribute("data-spy");
    if(act==="open-spyfall" || b.getAttribute("data-act")==="open-spyfall"){e.preventDefault();e.stopImmediatePropagation();open();return;}
    if(!act) return;
    e.preventDefault();e.stopImmediatePropagation();
    if(act==="home") home();
    if(act==="create") create();
    if(act==="start") start();
    if(act==="vote") vote(b.getAttribute("data-target"));
  },true);
  app.addEventListener("submit",function(e){
    if(e.target.id!=="spy-join") return;
    e.preventDefault();e.stopImmediatePropagation();
    var c=String(document.getElementById("spy-code").value||"").trim().toUpperCase();
    if(!/^SPY\d{3}$/.test(c)){toast("Kod SPY123 ko‘rinishida bo‘lishi kerak");return;}
    join(c);
  },true);
  window.addEventListener("load",function(){
    var params=new URLSearchParams(location.search);
    if(params.get("spy")) {open();join(params.get("spy").toUpperCase());}
  });
  timer=setInterval(function(){if(code && state && state.status!=="FINISHED") refresh();},3000);
})();