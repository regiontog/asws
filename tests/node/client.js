const WebSocket = require('ws');
const fs = require('fs');
const https = require('https');

const ws = new WebSocket('wss://localhost:3001', {
    perMessageDeflate: false,
    agent: new https.Agent(),
    cert: fs.readFileSync("../../certs/server.crt"),
    key: fs.readFileSync("../../certs/server.key")
});

ws.on('open', function open() {
    console.log("Pinging");
    ws.send("Hallo");
});

ws.on('pong', function incoming(data, flags) {
    console.log("Got _pong");
    console.log(data);
    console.log(flags);
});

ws.on('error', console.error);

ws.on('message',  function incoming(data, flags) {
    console.log("Got message");
    console.log(data);
    console.log(flags);
});