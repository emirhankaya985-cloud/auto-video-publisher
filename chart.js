/* Tiny local canvas chart renderer; no third-party CDN or network requests. */
class Chart {
  constructor(canvas, config) {
    this.canvas = canvas;
    this.config = config || {};
    this.draw();
  }
  destroy() {
    const c = this.canvas.getContext("2d");
    c.clearRect(0, 0, this.canvas.width, this.canvas.height);
  }
  draw() {
    const canvas = this.canvas;
    const rect = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.max(320, rect.width * ratio);
    canvas.height = Math.max(220, rect.height * ratio);
    const c = canvas.getContext("2d");
    c.scale(ratio, ratio);
    const w = canvas.width / ratio, h = canvas.height / ratio;
    c.clearRect(0, 0, w, h);
    const datasets = this.config.data?.datasets || [];
    if (this.config.type === "doughnut") return this.doughnut(c, w, h, datasets[0], this.config.data?.labels || []);
    if (this.config.type === "bar") return this.bar(c, w, h, datasets, this.config.data?.labels || []);
    this.line(c, w, h, datasets, this.config.data?.labels || []);
  }
  line(c, w, h, sets, labels) {
    const left = 45, right = 12, top = 18, bottom = 34;
    const values = sets.flatMap(s => (s.data || []).filter(Number.isFinite));
    if (!values.length || !labels.length) return this.empty(c, w, h);
    const min = Math.min(0, ...values), max = Math.max(1, ...values);
    c.strokeStyle = "#273143"; c.fillStyle = "#98a4b7"; c.lineWidth = 1;
    c.font = "11px system-ui";
    for (let i = 0; i <= 4; i++) {
      const y = top + (h - top - bottom) * i / 4;
      c.beginPath(); c.moveTo(left, y); c.lineTo(w - right, y); c.stroke();
      c.fillText(new Intl.NumberFormat("tr-TR", { notation: "compact" }).format(max - (max-min)*i/4), 2, y + 4);
    }
    const x = i => labels.length < 2 ? left + (w-left-right)/2 : left + (w-left-right)*i/(labels.length-1);
    const y = v => h-bottom-(v-min)/(max-min || 1)*(h-top-bottom);
    sets.forEach(s => {
      c.strokeStyle=s.borderColor||"#76a9ff"; c.lineWidth=2; c.beginPath();
      let pen=false;
      (s.data||[]).forEach((v,i)=>{ if (!Number.isFinite(v)) { pen=false; return; } if (!pen) { c.moveTo(x(i),y(v)); pen=true; } else c.lineTo(x(i),y(v)); });
      c.stroke();
    });
    if (labels.length) {
      c.fillStyle="#98a4b7";
      [0, Math.floor((labels.length-1)/2), labels.length-1].forEach(i => c.fillText(labels[i], Math.min(w-60,x(i)), h-8));
    }
  }
  bar(c,w,h,sets,labels) {
    const values=sets[0]?.data||[], valid=values.filter(Number.isFinite);
    if (!valid.length) return this.empty(c,w,h);
    const left=42,right=10,top=18,bottom=52,max=Math.max(1,...valid),slot=(w-left-right)/Math.max(values.length,1);
    c.strokeStyle="#273143";c.fillStyle="#98a4b7";c.font="10px system-ui";
    for(let i=0;i<=4;i++){const y=top+(h-top-bottom)*i/4;c.beginPath();c.moveTo(left,y);c.lineTo(w-right,y);c.stroke();c.fillText(new Intl.NumberFormat("tr-TR",{notation:"compact"}).format(max*(4-i)/4),2,y+3)}
    values.forEach((v,i)=>{if(!Number.isFinite(v))return;const bh=(h-top-bottom)*v/max,x=left+i*slot+slot*.18;c.fillStyle=["#76a9ff","#65ded2","#ffb86b","#d6a2ff","#ff7d9d","#b8db69"][i%6];c.fillRect(x,h-bottom-bh,slot*.64,bh);c.save();c.translate(x+slot*.32,h-bottom+8);c.rotate(-.45);c.fillStyle="#98a4b7";c.fillText((labels[i]||"").slice(0,18),0,0);c.restore()});
  }
  doughnut(c,w,h,set,labels) {
    const data=(set?.data||[]).map(v=>Number.isFinite(v)&&v>0?v:0);
    const total=data.reduce((a,b)=>a+b,0);
    if (!total) return this.empty(c,w,h);
    const colors=set.backgroundColor||["#76a9ff","#65ded2","#ffb86b","#d6a2ff","#ff7d9d","#b8db69"];
    const cx=w/2, cy=h/2-12, radius=Math.min(w,h)*.32;
    let angle=-Math.PI/2;
    data.forEach((v,i)=>{ if (!v) return; const end=angle+v/total*Math.PI*2; c.beginPath(); c.arc(cx,cy,radius,angle,end); c.arc(cx,cy,radius*.62,end,angle,true); c.closePath(); c.fillStyle=colors[i%colors.length]; c.fill(); angle=end; });
    c.fillStyle="#edf2fb"; c.font="bold 15px system-ui"; c.textAlign="center";
    c.fillText(new Intl.NumberFormat("tr-TR",{notation:"compact"}).format(total),cx,cy+5); c.textAlign="left";
    c.font="11px system-ui"; let x=8,y=h-18;
    labels.slice(0,8).forEach((label,i)=>{c.fillStyle=colors[i%colors.length];c.fillRect(x,y-8,8,8);c.fillStyle="#dfe7f5";c.fillText(label.slice(0,18),x+12,y);x+=Math.min(130,Math.max(68,label.length*6+22));if(x>w-100){x=8;y-=16;}});
  }
  empty(c,w,h) { c.fillStyle="#98a4b7"; c.font="13px system-ui"; c.textAlign="center"; c.fillText("Doğrulanmış veri yok",w/2,h/2); c.textAlign="left"; }
}
