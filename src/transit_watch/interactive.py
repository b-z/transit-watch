"""Interactive map (one self-contained HTML file for all events of a run).

The page carries each centerline densely sampled at two ellipsoidal heights (0 and 1000 m). The footprint moves
linearly with the observer's height, so the page can place the centerline for any height: it reads the ground
elevation of the point you tap (GSI DEM tiles in Japan, Open-Meteo elsewhere), adds the geoid height and the camera
height, and tells you how far the centerline is, which way to walk, and whether you are inside the visibility path.
With the phone's location (HTTPS only) it does the same for where you stand."""
import html
import json

from .geo import in_japan

LEAFLET = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4"


def event_data(e, S, tz):
    tr = e.get("track")
    target = S["sun"] if e["target"] == "S" else S["moon_illum"].format(illum=round(e["illum"] * 100))
    when = f"{e['time']:%m-%d} {S['weekdays'][e['time'].weekday()]} " + f"{e['time']:%H:%M:%S.%f}"[:-4]
    d = {
        "id": e["id"], "label": f"{e['time']:%m-%d %H:%M} {e['sat']} {S['sun_word'] if e['target'] == 'S' else S['moon_word']}",
        "title": f"{when} {e['sat']} {target} — {e['size']:.1f}″ {S['grade'][e['grade']]}",
        "spot": list(e["spot"]), "spotH": round(e["elev"], 1), "spotHell": round(e["h_ell"], 2),
        "spotT": e["t"].utc_datetime().timestamp() * 1000,
        "size": round(e["size"], 1), "width": round(e["width"], 3), "alt": round(e["alt"], 1), "az": round(e["az"], 1),
        "wx": S["verdict"][e["wx"]["verdict"]] if e.get("wx") and "verdict" in e["wx"] else "",
        "tf": [[round(a, 6), round(b, 6)] for a, b in e.get("tf_line") or []][::2],
        "tfOffset": round(e["cmp"]["offset_m"]) if e.get("cmp") else None,
        "tfDir": S["dirs"][e["cmp"]["dir"]] if e.get("cmp") else "",
        "jp": bool(in_japan(*e["spot"])), "onLand": bool(e["on_land"]),
    }
    if tr:
        d.update({"t0": tr["t0"].timestamp() * 1000, "dt": tr["dt"], "p0": tr["p0"], "p1": tr["p1"],
                  "sp": tr["sparse"], "geoid": tr["geoid"]})
    return d


def write(picks, home, S, cfg, path, generated):
    events = [event_data(e, S, cfg["location"]["timezone"]) for e in picks]
    data = {"events": events, "home": list(home), "tz": cfg["location"]["timezone"], "lang": cfg["output"]["language"],
            "S": S["imap"], "dirs": S["dirs"], "generated": generated, "fps": cfg["render"]["fps"]}
    page = TEMPLATE.replace("__TITLE__", html.escape(S["imap"]["title"])).replace("__LEAFLET__", LEAFLET) \
        .replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page)
    return path


TEMPLATE = r"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>__TITLE__</title>
<link rel="stylesheet" href="__LEAFLET__/leaflet.min.css">
<script src="__LEAFLET__/leaflet.min.js"></script>
<style>
:root{--bg:#f6f7f9;--panel:#ffffffee;--fg:#16191f;--muted:#5d6573;--line:#d0101f;--band:#d0101f;--tf:#e07800;
--me:#1667d9;--ok:#127a3a;--bad:#b3261e;--chip:#e8ebf0;--chipOn:#16191f;--chipOnFg:#fff;--border:#0000001a;
--mono:ui-monospace,"SF Mono",Menlo,monospace;--sans:-apple-system,BlinkMacSystemFont,"Hiragino Sans","PingFang SC","Noto Sans CJK SC",sans-serif}
@media (prefers-color-scheme:dark){:root{--bg:#101215;--panel:#181b20ee;--fg:#eef0f3;--muted:#9aa3b2;--chip:#262a31;
--chipOn:#eef0f3;--chipOnFg:#101215;--border:#ffffff1f;--ok:#4cc27a;--bad:#ff7a70;color-scheme:dark}}
html,body{height:100%;margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 var(--sans)}
#map{position:fixed;inset:0}
#top{position:fixed;left:0;right:0;top:0;z-index:1000;padding:calc(env(safe-area-inset-top,0px) + 8px) max(10px,env(safe-area-inset-right,0px)) 6px max(10px,env(safe-area-inset-left,0px));
display:flex;gap:6px;overflow-x:auto;scrollbar-width:none}
.chip{flex:none;border:1px solid var(--border);background:var(--panel);color:var(--fg);border-radius:16px;padding:5px 11px;font:inherit;font-size:13px;
backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);cursor:pointer;white-space:nowrap}
.chip[aria-pressed=true]{background:var(--chipOn);color:var(--chipOnFg)}
#tools{position:fixed;z-index:1000;right:max(10px,env(safe-area-inset-right,0px));top:calc(env(safe-area-inset-top,0px) + 52px);display:flex;flex-direction:column;gap:8px}
.tool{width:42px;height:42px;border-radius:21px;border:1px solid var(--border);background:var(--panel);color:var(--fg);font-size:18px;cursor:pointer;
backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px)}
.tool[aria-pressed=true]{background:var(--me);color:#fff}
#panel{position:fixed;z-index:1000;left:0;right:0;bottom:0;max-height:55%;overflow-y:auto;background:var(--panel);border-top:1px solid var(--border);
backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);padding:10px max(14px,env(safe-area-inset-right,0px)) calc(env(safe-area-inset-bottom,0px) + 12px) max(14px,env(safe-area-inset-left,0px))}
#panel.min .body{display:none}
#grip{display:block;width:100%;border:0;background:none;padding:0 0 6px;cursor:pointer}
#grip::before{content:"";display:block;margin:0 auto;width:38px;height:4px;border-radius:2px;background:var(--muted);opacity:.5}
h1{font-size:15px;margin:0 0 4px;font-weight:650;text-wrap:balance}
.meta{color:var(--muted);font-size:12.5px}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums}
.res{margin-top:10px;border-top:1px solid var(--border);padding-top:8px;display:grid;gap:4px}
.big{font-size:17px;font-weight:650}
.ok{color:var(--ok)} .bad{color:var(--bad)}
.row{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center}
label{color:var(--muted);font-size:12.5px} input{width:4.5em;font:inherit;padding:2px 4px;border:1px solid var(--border);border-radius:6px;background:transparent;color:var(--fg)}
a{color:var(--me)}
.hint{color:var(--muted);font-size:12.5px}
.leaflet-container{background:var(--bg)}
</style></head><body>
<div id="map"></div>
<div id="top" role="tablist"></div>
<div id="tools">
  <button class="tool" id="gps" aria-pressed="false">◎</button>
  <button class="tool" id="layer">⧉</button>
  <button class="tool" id="fit">⤢</button>
</div>
<div id="panel"><button id="grip" aria-label="toggle"></button><div class="body">
  <h1 id="title"></h1>
  <div class="meta" id="meta"></div>
  <div class="row" style="margin-top:6px"><label for="cam"></label><input id="cam" type="number" step="0.1" min="0" value="1.5"><span class="meta">m</span></div>
  <div id="out" class="res"></div>
</div></div>
<script>
const D=__DATA__;
const S=D.S, $=id=>document.getElementById(id);
document.querySelector('label[for=cam]').textContent=S.cam;
$("gps").title=S.gps; $("layer").title=S.layer; $("fit").title=S.fit;
const fmt=new Intl.DateTimeFormat(D.lang==="zh"?"zh-CN":D.lang,{timeZone:D.tz,hour12:false,month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",second:"2-digit"});
function tstr(ms){const r=Math.round(ms/10)*10;return fmt.format(new Date(Math.floor(r/1000)*1000))+"."+String(Math.floor((r%1000)/10)).padStart(2,"0");}
function mPerDeg(lat){const p=lat*Math.PI/180;return [111132.92-559.82*Math.cos(2*p)+1.175*Math.cos(4*p),111412.84*Math.cos(p)-93.5*Math.cos(3*p)];}
function dirName(dx,dy){return D.dirs[Math.round(((Math.atan2(dx,dy)*180/Math.PI)+360)%360/45)%8];}
function maps(p){return "https://www.google.com/maps/search/?api=1&query="+p[0].toFixed(6)+","+p[1].toFixed(6);}

// ---- geometry ----
function at(ev,i,h){const a=ev.p0[i],b=ev.p1[i],k=h/1000;return [a[0]+(b[0]-a[0])*k,a[1]+(b[1]-a[1])*k];}
function sparse(ev,x,key){const I=ev.sp.i,V=key==="geoid"?ev.geoid:ev.sp[key];let j=0;
  while(j<I.length-2&&I[j+1]<=x)j++;const u=Math.max(0,Math.min(1,(x-I[j])/((I[j+1]-I[j])||1)));
  let a=V[j],b=V[j+1]??a;if(key==="az"&&Math.abs(b-a)>180)b+=b<a?360:-360;return a+(b-a)*u;}
function foot(ev,P,h){const [ky,kx]=mPerDeg(P[0]);let best=null,q0=at(ev,0,h);
  let ax=(q0[1]-P[1])*kx,ay=(q0[0]-P[0])*ky;
  for(let i=0;i<ev.p0.length-1;i++){const q=at(ev,i+1,h),bx=(q[1]-P[1])*kx,by=(q[0]-P[0])*ky;
    const dx=bx-ax,dy=by-ay,L=dx*dx+dy*dy||1e-9,u=Math.max(0,Math.min(1,-(ax*dx+ay*dy)/L));
    const fx=ax+u*dx,fy=ay+u*dy,d=Math.hypot(fx,fy);
    if(!best||d<best.d)best={d,x:i+u,fx,fy,lat:P[0]+fy/ky,lon:P[1]+fx/kx};ax=bx;ay=by;}
  return best;}

// ---- elevation: GSI DEM PNG tiles in Japan, Open-Meteo elsewhere ----
const tiles=new Map();
function tileXY(lat,lon,z){const n=2**z,x=(lon+180)/360*n,r=lat*Math.PI/180,y=(1-Math.log(Math.tan(r)+1/Math.cos(r))/Math.PI)/2*n;return [x,y];}
function loadTile(layer,z,x,y){const k=layer+z+"/"+x+"/"+y;if(!tiles.has(k))tiles.set(k,(async()=>{
  const r=await fetch(`https://cyberjapandata.gsi.go.jp/xyz/${layer}/${z}/${x}/${y}.png`);if(!r.ok)return null;
  const bm=await createImageBitmap(await r.blob()),c=document.createElement("canvas");c.width=c.height=256;
  const g=c.getContext("2d",{willReadFrequently:true});g.drawImage(bm,0,0);return g.getImageData(0,0,256,256).data;})().catch(()=>null));
  return tiles.get(k);}
async function demGSI(lat,lon){for(const [layer,z,src] of [["dem5a_png",15,"DEM5A"],["dem5b_png",15,"DEM5B"],["dem_png",14,"DEM10B"]]){
  const [fx,fy]=tileXY(lat,lon,z),tx=Math.floor(fx),ty=Math.floor(fy),px=Math.floor((fx-tx)*256),py=Math.floor((fy-ty)*256);
  const t=await loadTile(layer,z,tx,ty);if(!t)continue;const o=(py*256+px)*4,v=t[o]*65536+t[o+1]*256+t[o+2];
  if(v===8388608)continue;return {h:(v<8388608?v:v-16777216)*0.01,src};}
  return {h:0,src:S.sea};}
const om=new Map();
async function demOM(lat,lon){const k=lat.toFixed(4)+","+lon.toFixed(4);if(!om.has(k))om.set(k,fetch(`https://api.open-meteo.com/v1/elevation?latitude=${lat.toFixed(5)}&longitude=${lon.toFixed(5)}`)
  .then(r=>r.json()).then(j=>({h:Math.max(0,j.elevation[0]),src:"Copernicus DEM"})).catch(()=>({h:0,src:"?"})));return om.get(k);}
function dem(ev,lat,lon){return ev.jp?demGSI(lat,lon):demOM(lat,lon);}
function cam(){const v=parseFloat($("cam").value);return isFinite(v)?v:0;}

// Root of g nearest to 0 (g(0) given): the line for height z sits at x_L(z) along a ray; we need the point whose own
// ground height puts it on the line. Plain iteration diverges on slopes steeper than the altitude angle, so bracket
// outwards and bisect.
async function root(g,g0){if(Math.abs(g0)<0.3)return 0;const dir=g0<0?1:-1;let a=0,ga=g0,step=Math.max(5,Math.abs(g0));
  for(let k=0;k<10;k++){const b=a+dir*step,gb=await g(b);
    if((gb>0)!==(ga>0)){let lo=a,hi=b,glo=ga;for(let j=0;j<16&&Math.abs(hi-lo)>0.3;j++){const m=(lo+hi)/2,gm=await g(m);
      if((gm>0)===(glo>0)){lo=m;glo=gm}else hi=m;}return (lo+hi)/2;}
    a=b;ga=gb;step*=2;}
  return null;}
function offset(P,x,ux,uy){const [ky,kx]=mPerDeg(P[0]);return [P[0]+x*uy/ky,P[1]+x*ux/kx];}

// The observer at P (ground height from the DEM) sees the centerline for height ground+geoid+camera: f.
// Walk target F: the nearest point, in the direction of f, that is on the centerline for its own ground height.
async function solve(ev,P){
  const g=await dem(ev,P[0],P[1]),N=sparse(ev,foot(ev,P,ev.spotHell).x,"geoid"),h=g.h+N+cam(),f=foot(ev,P,h);
  if(f.d<0.3)return {g,N,h,f,F:{lat:P[0],lon:P[1],d:0},gF:g};
  const ux=f.fx/f.d,uy=f.fy/f.d;
  const G=async x=>{const q=offset(P,x,ux,uy),z=(await dem(ev,q[0],q[1])).h,fz=foot(ev,P,z+N+cam());return x-(fz.fx*ux+fz.fy*uy);};
  const x=await root(G,-f.d),q=x==null?[f.lat,f.lon]:offset(P,x,ux,uy),gF=await dem(ev,q[0],q[1]);
  return {g,N,h,f,F:{lat:q[0],lon:q[1],d:x==null?f.d:x},gF};}

// ---- map ----
const map=L.map("map",{zoomControl:false,attributionControl:true});
const layers={gsi:L.tileLayer("https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png",{maxNativeZoom:18,maxZoom:20,attribution:"地理院タイル"}),
  photo:L.tileLayer("https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg",{maxNativeZoom:18,maxZoom:20,attribution:"地理院タイル（写真）"}),
  street:L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",{maxNativeZoom:19,maxZoom:20,attribution:"Tiles © Esri"}),
  sat:L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",{maxNativeZoom:19,maxZoom:20,attribution:"Tiles © Esri"})};
L.control.scale({imperial:false,position:"bottomleft"}).addTo(map);
let cur=null,overlay=L.layerGroup().addTo(map),pick=L.layerGroup().addTo(map),ground=L.layerGroup().addTo(map),base=null,photo=false;
function setBase(){if(base)map.removeLayer(base);base=(cur.jp?(photo?layers.photo:layers.gsi):(photo?layers.sat:layers.street)).addTo(map);base.bringToBack();}
const dot=(p,c,r=7)=>L.circleMarker(p,{radius:r,color:"#fff",weight:2,fillColor:c,fillOpacity:1});

function bandEdges(ev,h){const n=ev.p0.length,st=Math.max(1,Math.floor(n/300)),L1=[],L2=[];
  for(let i=0;i<n;i+=st){const a=at(ev,Math.max(0,i-1),h),b=at(ev,Math.min(n-1,i+1),h),p=at(ev,i,h),[ky,kx]=mPerDeg(p[0]);
    const dx=(b[1]-a[1])*kx,dy=(b[0]-a[0])*ky,l=Math.hypot(dx,dy)||1,w=sparse(ev,i,"width")*500;
    L1.push([p[0]+dx/l*w/ky,p[1]-dy/l*w/kx]);L2.push([p[0]-dx/l*w/ky,p[1]+dy/l*w/kx]);}
  return L1.concat(L2.reverse());}

function show(id){
  cur=D.events.find(e=>e.id===id)||D.events[0];if(!cur)return;
  document.querySelectorAll(".chip").forEach(c=>c.setAttribute("aria-pressed",c.dataset.id===cur.id));
  try{history.replaceState(null,"","#"+cur.id)}catch(e){}
  setBase();overlay.clearLayers();pick.clearLayers();ground.clearLayers();
  $("title").textContent=cur.title;
  $("meta").innerHTML=S.meta.replace("{h}",cur.spotH.toFixed(0)).replace("{w}",cur.width.toFixed(1)).replace("{alt}",cur.alt.toFixed(0)).replace("{az}",cur.az.toFixed(0))
    +(cur.wx?" · "+cur.wx:"")+(cur.tfOffset!=null?" · "+S.tf.replace("{m}",cur.tfOffset).replace("{dir}",cur.tfDir):"")
    +` · <a href="${maps(cur.spot)}" target="_blank" rel="noopener">${S.spotLink}</a>`;
  if(cur.p0){const be=bandEdges(cur,cur.spotHell),m=be.length/2;
    overlay.addLayer(L.polygon(be,{stroke:false,fillColor:"#d0101f",fillOpacity:.05,interactive:false}));
    for(const e of [be.slice(0,m),be.slice(m)])overlay.addLayer(L.polyline(e,{color:"#d0101f",weight:1,opacity:.6,dashArray:"2 6",interactive:false}));
    overlay.addLayer(L.polyline(cur.p0.map((_,i)=>at(cur,i,cur.spotHell)),{color:"#d0101f",weight:1.5,opacity:.55,interactive:false}));}
  if(cur.tf.length)overlay.addLayer(L.polyline(cur.tf,{color:"#e07800",weight:1.5,dashArray:"6 6",interactive:false}));
  overlay.addLayer(dot(D.home,"#1667d9",6).bindTooltip(S.home));
  overlay.addLayer(dot(cur.spot,"#d0101f").bindTooltip(S.spot));
  map.setView(cur.spot,13);
  $("out").innerHTML=`<div class="hint">${cur.p0?S.tap:S.noTrack}</div>`;
  drawGround();
  if(gpsOn&&lastFix)locate(lastFix);
}

// Bold line: the centerline at the ground height of each point (only when zoomed in; heights come from the DEM).
let gtok=0;
async function drawGround(){const ev=cur;if(!ev||!ev.p0)return;const tok=++gtok;ground.clearLayers();if(map.getZoom()<13)return;
  const b=map.getBounds().pad(.3),n=ev.p0.length,idx=[];
  for(let i=0;i<n;i++){const p=at(ev,i,ev.spotHell);if(b.contains(p))idx.push(i);}
  if(!idx.length)return;const st=Math.max(1,Math.ceil(idx.length/200)),pts=[];
  for(let j=0;j<idx.length;j+=st){const i=idx[j],N=sparse(ev,i,"geoid"),hs=ev.spotHell,p=at(ev,i,hs),[ky,kx]=mPerDeg(p[0]);
    const a=at(ev,Math.max(0,i-1),hs),b=at(ev,Math.min(n-1,i+1),hs),dx=(b[1]-a[1])*kx,dy=(b[0]-a[0])*ky,l=Math.hypot(dx,dy)||1;
    const ux=-dy/l,uy=dx/l,q=at(ev,i,hs+1000),k=((q[1]-p[1])*kx*ux+(q[0]-p[0])*ky*uy)/1000;
    const G=async x=>{const r=offset(p,x,ux,uy);return x-k*((await dem(ev,r[0],r[1])).h+N+cam()-hs);};
    const x=await root(G,await G(0));if(tok!==gtok)return;if(x!=null)pts.push(offset(p,x,ux,uy));}
  ground.addLayer(L.polyline(pts,{color:"#d0101f",weight:3,interactive:false}));}
map.on("moveend",drawGround);

async function report(P,label){const ev=cur;if(!ev.p0)return;const r=await solve(ev,P);if(ev!==cur)return;
  pick.clearLayers();
  const half=sparse(ev,r.f.x,"width")*500,d=r.f.d,inb=d<half,frac=d/half,dur=sparse(ev,r.f.x,"dur");
  const dF=r.F.d,[ky,kx]=mPerDeg(P[0]),dir=dirName((r.F.lon-P[1])*kx,(r.F.lat-P[0])*ky);
  const t=ev.t0+r.f.x*ev.dt*1000,dt=(t-ev.spotT)/1000;
  pick.addLayer(L.polyline([P,[r.F.lat,r.F.lon]],{color:"#1667d9",weight:2,dashArray:"4 5"}));
  pick.addLayer(dot([r.F.lat,r.F.lon],"#d0101f",5));
  if(label!=="gps")pick.addLayer(dot(P,"#1667d9",6));
  const L1=`<div class="big">${S.walk.replace("{dir}",dir).replace("{m}",`<span class="num">${dF<10?dF.toFixed(1):dF.toFixed(0)}</span>`)}</div>`;
  const L2=inb?`<div class="ok">${S.inBand.replace("{pct}",Math.round(frac*100)).replace("{s}",(dur*Math.sqrt(Math.max(0,1-frac*frac))).toFixed(2))}</div>`
                :`<div class="bad">${S.outBand.replace("{m}",(d-half).toFixed(0))}</div>`;
  const L3=`<div>${S.when.replace("{t}",`<span class="num">${tstr(t)}</span>`).replace("{dt}",(dt>=0?"+":"")+dt.toFixed(2))}</div>`;
  const L4=`<div class="meta">${S.here.replace("{H}",r.g.h.toFixed(1)).replace("{src}",r.g.src).replace("{N}",r.N.toFixed(1)).replace("{c}",cam().toFixed(1))
    .replace("{size}",sparse(ev,r.f.x,"size").toFixed(1)).replace("{alt}",sparse(ev,r.f.x,"alt").toFixed(0)).replace("{az}",sparse(ev,r.f.x,"az").toFixed(0))}</div>`;
  const L5=`<div class="meta">${S.target.replace("{H}",r.gF.h.toFixed(1))} · <span class="num">${r.F.lat.toFixed(6)}, ${r.F.lon.toFixed(6)}</span> · <a href="${maps([r.F.lat,r.F.lon])}" target="_blank" rel="noopener">Google Maps</a></div>`;
  $("out").innerHTML=(label==="gps"?`<div class="meta">${S.gpsAcc.replace("{m}",lastFix.coords.accuracy.toFixed(0))}</div>`:"")+L1+L2+L3+L4+L5;
  $("panel").classList.remove("min");}

map.on("click",e=>{if(gpsOn)toggleGps();report([e.latlng.lat,e.latlng.lng],"tap");});

// ---- GPS ----
let gpsOn=false,watch=null,lastFix=null,me=null,acc=null,busy=false;
function locate(pos){lastFix=pos;const P=[pos.coords.latitude,pos.coords.longitude];
  if(!me){me=dot(P,"#1667d9",7).addTo(map);acc=L.circle(P,{radius:pos.coords.accuracy,color:"#1667d9",weight:1,fillOpacity:.08}).addTo(map);map.setView(P,Math.max(map.getZoom(),16));}
  me.setLatLng(P);acc.setLatLng(P).setRadius(pos.coords.accuracy);
  if(!busy){busy=true;report(P,"gps").finally(()=>busy=false);}}
function toggleGps(){gpsOn=!gpsOn;$("gps").setAttribute("aria-pressed",gpsOn);
  if(gpsOn){if(!navigator.geolocation){$("out").innerHTML=`<div class="bad">${S.noGps}</div>`;gpsOn=false;return;}
    watch=navigator.geolocation.watchPosition(locate,err=>{$("out").innerHTML=`<div class="bad">${S.noGps} (${err.message})</div>`},{enableHighAccuracy:true,maximumAge:2000});}
  else{navigator.geolocation.clearWatch(watch);if(me){map.removeLayer(me);map.removeLayer(acc);me=acc=null;}}}
$("gps").onclick=toggleGps;
$("layer").onclick=()=>{photo=!photo;$("layer").setAttribute("aria-pressed",photo);setBase();};
$("fit").onclick=()=>{map.fitBounds(L.latLngBounds([D.home,cur.spot]).pad(.3));};
$("grip").onclick=()=>$("panel").classList.toggle("min");
$("cam").onchange=()=>{drawGround();if(lastFix&&gpsOn)locate(lastFix);};

const bar=$("top");
if(!D.events.length){$("title").textContent=S.none;map.setView(D.home,9);base=layers.gsi.addTo(map);}
D.events.forEach(e=>{const b=document.createElement("button");b.className="chip";b.dataset.id=e.id;b.textContent=e.label;b.onclick=()=>show(e.id);bar.appendChild(b);});
show(location.hash.slice(1));
</script></body></html>
"""
