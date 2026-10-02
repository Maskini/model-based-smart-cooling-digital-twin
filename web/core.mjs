// Browser counterpart of the Python thermal model and deterministic controller.
export const defaults = () => ({k_heat:.12,k_ambient:.012,k_fan:.25});
export function predict(t, ambient, fan, dt, p=defaults()) {
  if (![t,ambient,fan,dt,...Object.values(p)].every(Number.isFinite) || fan<0 || fan>100 || dt<0 || dt>3600) throw Error('Invalid model input');
  while(dt>0){const step=Math.min(1,dt);t+=step*(p.k_heat+p.k_ambient*(ambient-t)-p.k_fan*fan/100);dt-=step;}return t;
}
export function nextState(old,t,trend,target=30,healthy=true,powered=true){
  if(!healthy||!Number.isFinite(t))return 'FAULT';
  if(t>=40||(old==='OVERHEATING'&&t>39))return 'OVERHEATING';
  if(!powered)return 'OFF';
  if(t>=target||(old==='COOLING'&&t>target-1))return 'COOLING';
  if(trend>.02||(old==='HEATING'&&trend>.005))return 'HEATING';return 'NORMAL';
}
export function command(state,t,mode='AUTO',manual=0,target=30){
  let desired=state==='OFF'?0:mode==='MANUAL'?manual:state==='COOLING'?20+20*(t-target):0;
  if(['FAULT','OVERHEATING'].includes(state)||t==null||!Number.isFinite(t)||t>=40||!Number.isFinite(desired))return 100;
  return Math.min(100,Math.max(0,desired));
}
export function explanation(s){
 const t=s.telemetry?.temperature,c=s.control;
 if(t==null)return 'Waiting for the first hardware reading. You can use Simulation immediately.';
 if(s.state==='FAULT')return 'Sensor or connection health failed. The deterministic controller requests 100% cooling as a safety fallback.';
 if(s.state==='OVERHEATING')return `Temperature reached ${t.toFixed(1)} °C. The 40 °C safety limit overrides manual demand and requests maximum cooling.`;
 if(s.state==='OFF')return 'Simulation is paused. Start it or run the guided demo to see the model respond.';
 if(c.mode==='MANUAL')return `Manual demand is ${c.manual_fan}%. The safety-validated command is ${s.fan.toFixed(0)}%.`;
 if(s.state==='COOLING')return `Temperature is ${t.toFixed(1)} °C against a ${c.setpoint} °C target. Cooling is ${s.fan.toFixed(0)}%; it switches off at or below ${(c.setpoint-1).toFixed(1)} °C.`;
 return s.state==='HEATING'?`Temperature is rising. Cooling starts at ${c.setpoint} °C; the fixed safety limit is 40 °C.`:'Temperature is within the normal range. Cooling is off.';
}
export class SimulationSensorSource {
 constructor(){this.reset();}
 reset(){this.running=false;this.t=27;this.humidity=47;this.ambient=24;this.heat=.12;this.effect=.25;this.noise=0;this.fault=false;this.control={mode:'AUTO',manual_fan:0,setpoint:30};this.p=defaults();this.state='OFF';this.fan=0;this.history=[];this.transitions=[];this.events=[];this.errors=[];this.prediction=null;this.phase='IDLE';this.elapsed=0;this.pending=null;this.lastCalibration=-Infinity;this.lastAssessment=0;this.degradedWindows=0;this.sample(Date.now()/1000,0);}
 event(text){this.events.push({timestamp:Date.now()/1000,text});this.events=this.events.slice(-60);}
 start(){this.running=true;this.prediction=null;}
 stop(){this.running=false;this.phase='IDLE';this.control.mode='AUTO';this.fan=0;this.prediction=null;this.sample(Date.now()/1000,0);}
 demo(){this.reset();this.running=true;this.heat=0;this.phase='NORMAL';this.phaseAt=0;this.event('Normal temperature · cooling off');}
 controls(c){if(!['AUTO','MANUAL'].includes(c.mode)||!Number.isFinite(c.manual_fan)||c.manual_fan<0||c.manual_fan>100||!Number.isFinite(c.setpoint)||c.setpoint<20||c.setpoint>35)throw Error('Invalid control settings');this.control={...c};this.phase='IDLE';this.state=nextState(this.state,this.t,0,c.setpoint,!this.fault,this.running);this.fan=command(this.state,this.t,c.mode,c.manual_fan,c.setpoint);}
 edit(v){for(const [key,value]of Object.entries(v)){const bounds={t:[-40,60],humidity:[0,100],heat:[0,2],ambient:[-10,50],effect:[0,3],noise:[0,1]}[key];if(bounds&&(!Number.isFinite(value)||value<bounds[0]||value>bounds[1]))throw Error('Invalid '+key);if(!bounds&&key!=='fault')throw Error('Unknown setting');}Object.assign(this,v);this.phase='IDLE';this.history=[];this.errors=[];this.prediction=null;this.pending=null;this.sample(Date.now()/1000,0);}
 tick(now,dt=1){if(!this.running)return;this.elapsed+=dt;
  if(this.phase==='NORMAL'&&this.elapsed-this.phaseAt>=2){this.heat=1.9;this.phase='HEATING';this.phaseAt=this.elapsed;this.event('Heat load increasing · controller reacts');}
  else if(this.phase==='HEATING'&&this.t>=40){this.phase='OVERHEATING';this.phaseAt=this.elapsed;this.event('40 °C crossed · maximum cooling activated');}
  else if(this.phase==='OVERHEATING'&&this.elapsed-this.phaseAt>=2){this.heat=0;this.effect=1.5;this.phase='RECOVERING';this.event('Heat removed · cooling toward target');}
  else if(this.phase==='RECOVERING'&&this.fan===0){this.phase='COMPLETE';this.heat=.02;this.event('Recovered · cooling off · demo complete');}
  this.sample(now,dt);
  if(this.elapsed-this.lastAssessment>=10){this.lastAssessment=this.elapsed;this.degradedWindows=this.mae>.06?this.degradedWindows+1:0;
   if(this.degradedWindows>=3&&!this.pending&&this.elapsed-this.lastCalibration>=180&&!['FAULT','OVERHEATING'].includes(this.state)){this.event('Supervisor detected persistent model error · evaluating calibration');this.calibrate();}
  }
 }
 sample(now,dt){const previous=this.t;const applied=this.fault||this.t>=40?100:this.fan;
  if(this.running)this.t=predict(this.t,this.ambient,applied,dt,{k_heat:this.heat,k_ambient:.012,k_fan:this.effect});
  this.t=Math.min(125,Math.max(-40,this.t));const measured=Math.min(125,Math.max(-40,this.t+(this.noise?(Math.random()-.5)*2*this.noise:0)));
  const old=this.state;this.state=nextState(old,measured,dt?(this.t-previous)/dt:0,this.control.setpoint,!this.fault,this.running);
  if(old!==this.state){this.transitions.push({timestamp:now,previous:old,current:this.state});this.transitions=this.transitions.slice(-60);}
  this.fan=command(this.state,measured,this.control.mode,this.control.manual_fan,this.control.setpoint);
  const matched=this.prediction!=null&&dt>0&&!this.fault?measured-this.prediction:null;
  if(matched!=null){this.errors.push(matched);this.errors=this.errors.slice(-30);}
  if(this.fault){this.errors=[];this.prediction=null;}
  this.telemetry={timestamp:now,device_id:'browser-demo',temperature:measured,humidity:this.humidity,ambient_temperature:this.ambient,fan_speed:this.running?applied:0,sensor_ok:!this.fault,powered:this.running};
  const row={...this.telemetry,predicted_temperature:this.prediction,prediction_error:matched};this.history.push(row);this.history=this.history.slice(-600);
  this.prediction=this.running&&!this.fault?predict(measured,this.ambient,this.fan,1,this.p):null;
  this.error=matched;this.mae=this.errors.length?this.errors.reduce((a,b)=>a+Math.abs(b),0)/this.errors.length:null;
  if(this.pending&&dt>0){const q=this.pending;const a=q.last;const actual=(measured-a.temperature)/dt;const err=p=>Math.abs((p.k_heat+p.k_ambient*(a.ambient_temperature-a.temperature)-p.k_fan*applied/100-actual)*dt);q.old.push(err(q.previous));q.new.push(err(this.p));q.last=this.telemetry;
   if(this.fault||q.new.length>=30){if(this.fault||q.new.reduce((a,b)=>a+b,0)>q.old.reduce((a,b)=>a+b,0)*.95){this.p=q.previous;this.event('Calibration rolled back after fresh-data verification');}else this.event('Calibration verified on 30 fresh intervals');this.pending=null;}
  }
 }
 calibrate(){if(!this.running||['FAULT','OVERHEATING'].includes(this.state))throw Error('Calibration requires a running, healthy system below the safety limit.');if(this.pending)throw Error('Calibration is awaiting fresh-data verification.');if(this.elapsed-this.lastCalibration<180)throw Error('Calibration cooldown is active.');this.lastCalibration=this.elapsed;
  const rows=[];for(let i=1;i<this.history.length;i++){const a=this.history[i-1],b=this.history[i],dt=b.timestamp-a.timestamp;if(dt>=.2&&dt<=3&&a.sensor_ok&&b.sensor_ok&&a.powered&&b.powered)rows.push({x:-b.fan_speed/100,y:(b.temperature-a.temperature)/dt-this.p.k_ambient*(a.ambient_temperature-a.temperature),dt});}
  if(rows.length<60){this.event('Calibration: insufficient data (60 healthy intervals required)');return;}
  const split=Math.floor(rows.length*.7),train=rows.slice(0,split),valid=rows.slice(split),xs=train.map(r=>r.x);
  if(Math.max(...xs)-Math.min(...xs)<.15){this.event('Calibration: vary heat load and fan demand to provide excitation');return;}
  const mx=xs.reduce((a,b)=>a+b,0)/train.length,my=train.reduce((a,b)=>a+b.y,0)/train.length;
  const den=train.reduce((a,r)=>a+(r.x-mx)**2,0);if(den<1e-9){this.event('Calibration: insufficient independent data');return;}
  const kfan=train.reduce((a,r)=>a+(r.x-mx)*(r.y-my),0)/den,kheat=my-kfan*mx;
  if(kfan<.001||kfan>3||kheat<0||kheat>2){this.event('Calibration candidate rejected: outside physical bounds');return;}
  const candidate={...this.p,k_heat:kheat,k_fan:kfan};const mae=p=>valid.reduce((a,r)=>a+Math.abs((p.k_heat+p.k_fan*r.x-r.y)*r.dt),0)/valid.length;
  if(mae(this.p)<=.005||mae(candidate)>mae(this.p)*.85){this.event('Calibration rejected: less than 15% holdout improvement');return;}
  this.pending={previous:{...this.p},last:this.telemetry,old:[],new:[]};this.p=candidate;this.errors=[];this.prediction=null;this.event('Bounded calibration applied · verifying 30 fresh intervals (ambient coefficient held fixed)');
 }
 snapshot(){return {telemetry:this.telemetry,state:this.state,fan:this.fan,control:this.control,parameters:this.p,history:this.history,prediction:this.prediction,error:this.error,mae:this.mae,events:this.events,transitions:this.transitions,running:this.running,phase:this.phase,modelHealth:this.fault?'FAULT':this.pending?'CALIBRATING':this.mae==null?'WATCH':this.mae>.06?'DEGRADED':'HEALTHY',connection:{activity:this.running?'RECEIVING':'PAUSED',transport:'BROWSER',device_id:'browser-demo'},analysis:explanation(this)};}
}
export class Esp32SensorSource {
 constructor(url){this.url=url.replace(/\/$/,'');this.token='';}
 async request(path,method='GET',body){const r=await fetch(this.url+path,{method,headers:{...(body?{'Content-Type':'application/json'}:{}),...(this.token?{Authorization:'Bearer '+this.token}:{})},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(12000),cache:'no-store'});if(!r.ok){let detail='Backend request failed';try{detail=(await r.json()).detail||detail;}catch{}throw Error(typeof detail==='string'?detail:JSON.stringify(detail));}return r.json();}
 async snapshot(){const d=await this.request('/api/live/state'),s=d.state;return {telemetry:s.telemetry,state:s.state,fan:s.fan_command,control:d.control,parameters:d.parameters,history:d.history.map(t=>({...t,predicted_temperature:d.predictions.find(p=>Math.abs(p.target_timestamp-t.timestamp)<.5)?.predicted_temperature})),prediction:s.prediction?.predicted_temperature,error:s.metrics.prediction_error,mae:s.metrics.rolling_mae,events:d.agent_events.map(e=>({timestamp:e.timestamp,text:e.reason+' · '+e.actual_outcome})),transitions:d.transitions,running:d.device_status==='Online',phase:'IDLE',modelHealth:s.model_health,connection:d.connection,analysis:d.analysis.summary};}
 controls(c){return this.request('/api/live/control','PUT',c);}
 calibrate(){return this.request('/api/live/calibration','POST');}
}
