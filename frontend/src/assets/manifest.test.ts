import { describe, expect, it } from "vitest";

import { TRIAL_SPRITES } from "./manifest";

describe("TRIAL_SPRITES", () => {
  const sprites = Object.entries(TRIAL_SPRITES).flatMap(([role, poses]) =>
    Object.entries(poses).map(([pose, sprite]) => ({ name: `${role}.${pose}`, sprite })),
  );
  // 口を開けて描いた立ち絵は下あごを動かさない(口を閉じた版の口まわりで口パクする)
  const open = new Set(["prosecutor.igiari"]);

  it.each(sprites.filter((s) => !open.has(s.name)))("$name は口パクの口の位置を持ち、立ち絵の中に収まる", ({ sprite }) => {
    const mouth = sprite.mouth;
    expect(mouth).toBeDefined();
    if (!mouth) return;
    expect(mouth.x - mouth.width).toBeGreaterThanOrEqual(0);
    expect(mouth.x + mouth.width).toBeLessThanOrEqual(sprite.width);
    expect(mouth.y).toBeGreaterThan(0);
    expect(mouth.y + mouth.jaw + mouth.open).toBeLessThanOrEqual(sprite.height);
    expect(mouth.open).toBeGreaterThan(0);
  });

  it("口を開けて描いた立ち絵は、口を閉じた版の口まわりを立ち絵の中に持つ", () => {
    const sprite = TRIAL_SPRITES.prosecutor.igiari;
    expect(sprite.mouth).toBeUndefined();
    const closed = sprite.closedMouth;
    expect(closed).toBeDefined();
    if (!closed) return;
    expect(closed.src).toContain("tama_igiari_mouth.png");
    expect(closed.x).toBeGreaterThanOrEqual(0);
    expect(closed.y).toBeGreaterThanOrEqual(0);
    expect(closed.x + closed.width).toBeLessThanOrEqual(sprite.width);
    expect(closed.y + closed.height).toBeLessThanOrEqual(sprite.height);
  });
});
