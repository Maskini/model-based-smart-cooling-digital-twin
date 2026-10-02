import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  predict,
  nextState,
  command,
  SimulationSensorSource,
} from "../../web/core.mjs";
const vectors = JSON.parse(
  readFileSync(new URL("./parity.json", import.meta.url)),
);
test("Python parity: state machine, safety commands and thermal integration", () => {
  for (const v of vectors.control) {
    assert.equal(nextState(...v.input), v.state);
    assert.equal(
      command(v.state, v.input[1], v.mode, v.manual, v.input[3]),
      v.fan,
    );
  }
  for (const v of vectors.thermal)
    assert.ok(Math.abs(predict(...v.input) - v.output) < 1e-9);
});
test("Local demo completes, reaches safety threshold, recovers without fault", () => {
  const s = new SimulationSensorSource();
  s.demo();
  const states = new Set();
  for (let i = 1; i <= 35; i++) {
    s.tick(1000 + i);
    states.add(s.state);
    if (s.phase === "COMPLETE") break;
  }
  assert.equal(s.phase, "COMPLETE");
  assert(states.has("OVERHEATING"));
  assert(!states.has("FAULT"));
  assert.equal(s.fan, 0);
  assert(s.t <= 29);
  assert(s.elapsed <= 30);
});
test("Manual requests cannot override overheating or sensor fault", () => {
  const s = new SimulationSensorSource();
  s.start();
  s.edit({ t: 42 });
  s.controls({ mode: "MANUAL", manual_fan: 0, setpoint: 30 });
  assert.equal(s.fan, 100);
  s.edit({ t: 27, fault: true });
  assert.equal(s.state, "FAULT");
  assert.equal(s.fan, 100);
  s.stop();
  s.edit({ fault: false, t: 27 });
  s.controls({ mode: "MANUAL", manual_fan: 100, setpoint: 30 });
  assert.equal(s.fan, 0);
});
test("Pause freezes history and reset clears state", () => {
  const s = new SimulationSensorSource();
  s.start();
  s.tick(1001);
  s.stop();
  const before = JSON.stringify(s.snapshot());
  s.tick(2000);
  assert.equal(JSON.stringify(s.snapshot()), before);
  s.demo();
  s.controls({ mode: "MANUAL", manual_fan: 25, setpoint: 30 });
  assert.equal(s.phase, "IDLE");
  s.reset();
  assert.equal(s.t, 27);
  assert.equal(s.events.length, 0);
  assert.equal(s.running, false);
});
test("Calibration requires safe running state and meaningful data", () => {
  const s = new SimulationSensorSource();
  assert.throws(() => s.calibrate());
  s.start();
  s.calibrate();
  assert(s.events.at(-1).text.includes("insufficient"));
  assert.throws(() => s.calibrate(), /cooldown/);
  s.edit({ t: 42 });
  assert.throws(() => s.calibrate(), /healthy/);
});
test("Invalid settings are rejected before changing state", () => {
  const s = new SimulationSensorSource();
  assert.throws(() => s.edit({ t: NaN }));
  assert.equal(s.t, 27);
  assert.throws(() =>
    s.controls({ mode: "AUTO", manual_fan: 0, setpoint: 100 }),
  );
  assert.equal(s.control.setpoint, 30);
});
test("Calibration accepts a bounded improving model then verifies fresh observations", () => {
  const s = new SimulationSensorSource();
  s.start();
  s.heat = 0.3;
  s.effect = 0.7;
  s.p = { k_heat: 0.1, k_ambient: 0.012, k_fan: 0.2 };
  s.history = [];
  let t = 30;
  for (let i = 0; i < 90; i++) {
    const fan = i % 20 < 10 ? 0 : 100;
    s.history.push({
      timestamp: 1000 + i,
      temperature: t,
      ambient_temperature: 24,
      fan_speed: fan,
      sensor_ok: true,
      powered: true,
      device_id: "browser-demo",
    });
    const nextFan = (i + 1) % 20 < 10 ? 0 : 100;
    t += 0.3 + 0.012 * (24 - t) - (0.7 * nextFan) / 100;
  }
  s.telemetry = s.history.at(-1);
  s.t = s.telemetry.temperature;
  s.calibrate();
  assert(s.pending);
  assert(Math.abs(s.p.k_heat - 0.3) < 1e-8);
  assert(Math.abs(s.p.k_fan - 0.7) < 1e-8);
  for (let i = 1; i <= 30; i++) s.tick(1089 + i);
  assert.equal(s.pending, null);
  assert(s.events.some((e) => e.text.includes("verified")));
});
