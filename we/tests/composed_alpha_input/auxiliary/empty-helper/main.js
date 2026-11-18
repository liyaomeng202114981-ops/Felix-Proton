// SPDX-License-Identifier: BSD-3-Clause; Copyright 2026 Felix Li
const {app,BrowserWindow}=require('electron');let parent,helper;
app.setPath('userData','C:\\felix-empty-input-fixture');
app.whenReady().then(async()=>{
 parent=new BrowserWindow({show:false,frame:false,x:30,y:30,width:400,height:300,backgroundColor:'#225577',title:'Felix empty control parent'});
 await parent.loadURL('data:text/html,<body style="margin:0;background:%23225577">opaque control');parent.showInactive();
 helper=new BrowserWindow({show:false,parent,frame:false,resizable:false,x:600,y:80,width:300,height:240,transparent:true,backgroundColor:'#00000000',title:'Felix empty transparent helper'});
 await helper.loadURL('data:text/html,<title>Felix empty transparent helper</title><style>html,body{margin:0;overflow:hidden;background:transparent}</style><canvas width=300 height=240 id=c></canvas><script>const ctx=c.getContext("2d");let frames=0;function tick(){ctx.clearRect(0,0,300,240);if(frames++<60){ctx.fillStyle="rgb(70,130,190)";ctx.fillRect(20,20,80,80)}requestAnimationFrame(tick)}tick()</script>');helper.showInactive();setTimeout(()=>helper.setIgnoreMouseEvents(true),500);
 setTimeout(()=>app.quit(),90000);
});
