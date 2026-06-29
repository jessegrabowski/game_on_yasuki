import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import {
  clampSquareBox,
  boxToCrop,
  centeredBox,
  cropToBox,
} from '../../../src/yasuki_web/static/site/card-crop.js';

describe('clampSquareBox', () => {
  it('caps the side at the shorter dimension', () => {
    assert.equal(clampSquareBox({ x: 0, y: 0, size: 9999 }, 280, 397).size, 280);
  });

  it('enforces a minimum side', () => {
    assert.equal(clampSquareBox({ x: 0, y: 0, size: 1 }, 200, 400).size, 200 * 0.12);
  });

  it('keeps the box inside the bounds', () => {
    const box = clampSquareBox({ x: -50, y: 1000, size: 100 }, 200, 400);
    assert.equal(box.x, 0);
    assert.equal(box.y, 300); // 400 - 100
  });
});

describe('boxToCrop', () => {
  it('expresses the box as fractions of the canvas', () => {
    assert.deepEqual(boxToCrop({ x: 0, y: 0, size: 100 }, 200, 400), {
      left: 0,
      top: 0,
      right: 0.5,
      bottom: 0.25,
    });
  });
});

describe('centeredBox', () => {
  it('is square, centered, and within bounds', () => {
    const box = centeredBox(200, 400);
    assert.equal(box.x, (200 - box.size) / 2);
    assert.equal(box.y, (400 - box.size) / 2);
    assert.ok(box.size > 0 && box.x >= 0 && box.x + box.size <= 200);
  });
});

describe('cropToBox', () => {
  it('inverts boxToCrop', () => {
    const box = { x: 50, y: 100, size: 100 }; // fractions land on exact floats
    assert.deepEqual(cropToBox(boxToCrop(box, 200, 400), 200, 400), box);
  });
});
