// SPDX-License-Identifier: BSD-3-Clause; Copyright 2026 Felix Li
const {app,BrowserWindow}=require('electron');
const fs=require('fs');
const wins=[];
app.setPath('userData','C:\\felix-transparency-fixture');
if(process.argv.includes('--software-ui')) app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
 const shared={show:false,frame:false,resizable:false,webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true}};
 const main=new BrowserWindow({...shared,title:'Felix opaque Electron control',x:40,y:40,width:500,height:300,backgroundColor:'#225577'});wins.push(main);
 const overlay=new BrowserWindow({...shared,title:'Felix transparent owned overlay',parent:main,x:80,y:410,width:500,height:300,transparent:true,backgroundColor:'#00000000'});wins.push(overlay);
 const popup=new BrowserWindow({...shared,title:'Felix transparent popup',x:620,y:60,width:300,height:500,transparent:true,backgroundColor:'#00000000'});wins.push(popup);
 for(const win of wins){await win.loadFile(__dirname+'/fixture.html');win.showInactive();}
 setTimeout(()=>overlay.setIgnoreMouseEvents(true),1000);
 setTimeout(()=>require('child_process').execFile('Z:\\opt\\felix-materials\\window_metadata.exe',[process.execPath,'Z:\\opt\\felix-case\\electron-metadata.json'],{windowsHide:true},()=>{}),3000);
 fs.writeFileSync('Z:\\opt\\felix-case\\electron-fixture-ready.json',JSON.stringify({time_epoch_ms:Date.now(),versions:process.versions,windows:wins.map(w=>({title:w.getTitle(),bounds:w.getBounds()}))}));
 setTimeout(()=>app.quit(),180000);
});
app.on('window-all-closed',()=>app.quit());
