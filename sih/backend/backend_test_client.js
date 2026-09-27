#!/usr/bin/env node
// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin - Backend Test Client
// ══════════════════════════════════════════════════════════════════════════════
//
// This standalone test client connects to the backend WebSocket server
// and measures end-to-end throughput and latency.
//
// Usage:
//   node backend_test_client.js
//   node backend_test_client.js --port 8080 --frames 100
//
// ══════════════════════════════════════════════════════════════════════════════

const WebSocket = require('ws');
const http = require('http');

// ─── Configuration ──────────────────────────────────────────────────────────

const args = process.argv.slice(2);
const WS_PORT = getArg('--port', 8080);
const HTTP_PORT = getArg('--http-port', 8081);
const NUM_FRAMES = getArg('--frames', 50);
const MEASURE_LATENCY = args.includes('--latency');

function getArg(name, defaultValue) {
  const idx = args.indexOf(name);
  if (idx !== -1 && idx + 1 < args.length) {
    return parseInt(args[idx + 1], 10);
  }
  return defaultValue;
}

// ─── Test State ─────────────────────────────────────────────────────────────

let ws = null;
let framesReceived = 0;
let framesStart = null;
let latencies = [];
let firstFrameTime = null;
let lastFrameTime = null;

// ─── WebSocket Client ──────────────────────────────────────────────────────

function connectWebSocket() {
  console.log('═══════════════════════════════════════════════════════════════════════════');
  console.log('  Aero Piston Engine Digital Twin - Backend Test Client');
  console.log('═══════════════════════════════════════════════════════════════════════════\n');

  console.log(`Connecting to ws://localhost:${WS_PORT}...`);

  ws = new WebSocket(`ws://localhost:${WS_PORT}`);

  ws.on('open', () => {
    console.log('✓ Connected to server\n');
    console.log('Waiting for telemetry frames...');
    console.log(`(Will collect ${NUM_FRAMES} frames)\n`);

    framesStart = Date.now();
    ws.send(JSON.stringify({ action: 'PING' }));
  });

  ws.on('message', (data) => {
    try {
      const message = JSON.parse(data.toString());
      handleMessage(message);
    } catch (err) {
      console.error('Failed to parse message:', err.message);
    }
  });

  ws.on('close', (code, reason) => {
    console.log(`\nConnection closed (code: ${code})`);
    printResults();
  });

  ws.on('error', (err) => {
    console.error('Connection error:', err.message);
    console.log('\nMake sure the backend server is running:');
    console.log('  cd backend && npm run dev');
    process.exit(1);
  });
}

// ─── Message Handling ──────────────────────────────────────────────────────

function handleMessage(message) {
  if (message.type === 'WELCOME') {
    console.log(`Server welcome: Client ID = ${message.clientId}`);
    console.log(`Server time: ${message.serverTime}\n`);
    return;
  }

  if (message.type === 'PONG') {
    console.log(`Pong received: ${message.serverTime}\n`);
    return;
  }

  if (message.type === 'STATS') {
    console.log('\n--- Server Statistics ---');
    console.log(JSON.stringify(message, null, 2));
    return;
  }

  if (message.type === 'ERROR') {
    console.error('Server error:', message.message);
    return;
  }

  // Telemetry frame
  if (message.frame_id !== undefined) {
    const receiveTime = Date.now();
    
    if (!firstFrameTime) {
      firstFrameTime = receiveTime;
    }
    lastFrameTime = receiveTime;

    framesReceived++;

    // Calculate latency if frame has timestamp
    if (message.timestamp && MEASURE_LATENCY) {
      const frameTime = new Date(message.timestamp).getTime();
      const latency = receiveTime - frameTime;
      latencies.push(latency);
    }

    // Progress indicator
    if (framesReceived % 10 === 0 || framesReceived === NUM_FRAMES) {
      const elapsed = (receiveTime - framesStart) / 1000;
      const fps = framesReceived / elapsed;
      process.stdout.write(`\r  Frames: ${framesReceived}/${NUM_FRAMES} | FPS: ${fps.toFixed(1)} | Elapsed: ${elapsed.toFixed(1)}s`);
    }

    // Check if we've collected enough frames
    if (framesReceived >= NUM_FRAMES) {
      console.log('\n');
      printResults();
      
      // Send a test command
      sendTestCommand();
    }
  }
}

// ─── Test Commands ─────────────────────────────────────────────────────────

function sendTestCommand() {
  console.log('Sending test command (TRIGGER_FAULT)...');
  
  ws.send(JSON.stringify({
    action: 'TRIGGER_FAULT',
    fault: 'PISTON_RING_WEAR',
    severity: 0.3,
  }));

  // Wait a bit then clear faults
  setTimeout(() => {
    console.log('Sending CLEAR_FAULTS command...');
    ws.send(JSON.stringify({ action: 'CLEAR_FAULTS' }));

    // Request server stats
    setTimeout(() => {
      console.log('Requesting server stats...');
      ws.send(JSON.stringify({ action: 'GET_STATS' }));

      // Close after receiving stats
      setTimeout(() => {
        console.log('\nTest complete. Closing connection...');
        ws.close();
      }, 1000);
    }, 500);
  }, 1000);
}

// ─── Results ───────────────────────────────────────────────────────────────

function printResults() {
  if (framesReceived === 0) {
    console.log('\nNo frames received. Check if server is running.');
    return;
  }

  const totalTime = (lastFrameTime - firstFrameTime) / 1000;
  const avgFps = framesReceived / totalTime;

  console.log('═══════════════════════════════════════════════════════════════════════════');
  console.log('  Test Results');
  console.log('═══════════════════════════════════════════════════════════════════════════\n');

  console.log('--- Throughput ---');
  console.log(`  Frames received:  ${framesReceived}`);
  console.log(`  Total time:       ${totalTime.toFixed(2)}s`);
  console.log(`  Average FPS:      ${avgFps.toFixed(1)} Hz`);
  console.log(`  Expected:         10 Hz`);
  console.log(`  Status:           ${avgFps >= 9.5 ? '✓ PASS' : '✗ FAIL'}\n`);

  if (latencies.length > 0) {
    const sortedLatencies = [...latencies].sort((a, b) => a - b);
    const minLatency = sortedLatencies[0];
    const maxLatency = sortedLatencies[sortedLatencies.length - 1];
    const avgLatency = latencies.reduce((a, b) => a + b, 0) / latencies.length;
    const p50Latency = sortedLatencies[Math.floor(sortedLatencies.length * 0.5)];
    const p95Latency = sortedLatencies[Math.floor(sortedLatencies.length * 0.95)];
    const p99Latency = sortedLatencies[Math.floor(sortedLatencies.length * 0.99)];

    console.log('--- Latency (End-to-End) ---');
    console.log(`  Min:    ${minLatency.toFixed(2)}ms`);
    console.log(`  Avg:    ${avgLatency.toFixed(2)}ms`);
    console.log(`  P50:    ${p50Latency.toFixed(2)}ms`);
    console.log(`  P95:    ${p95Latency.toFixed(2)}ms`);
    console.log(`  P99:    ${p99Latency.toFixed(2)}ms`);
    console.log(`  Max:    ${maxLatency.toFixed(2)}ms`);
    console.log(`  Status: ${p95Latency < 50 ? '✓ PASS (<50ms)' : '✗ FAIL (>=50ms)'}\n`);
  }

  console.log('═══════════════════════════════════════════════════════════════════════════\n');
}

// ─── HTTP Health Check ─────────────────────────────────────────────────────

function checkHealth() {
  return new Promise((resolve, reject) => {
    const req = http.get(`http://localhost:${HTTP_PORT}/health`, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (err) {
          reject(err);
        }
      });
    });

    req.on('error', reject);
    req.setTimeout(2000, () => {
      req.destroy();
      reject(new Error('Timeout'));
    });
  });
}

// ─── Main ──────────────────────────────────────────────────────────────────

async function main() {
  // Try health check first
  try {
    console.log('Checking HTTP health endpoint...');
    const health = await checkHealth();
    console.log('✓ Server is healthy\n');
    console.log(JSON.stringify(health, null, 2));
    console.log('');
  } catch (err) {
    console.log('⚠ HTTP health check failed (server may not be running)\n');
  }

  // Connect via WebSocket
  connectWebSocket();
}

main().catch((err) => {
  console.error('Fatal error:', err);
  process.exit(1);
});
