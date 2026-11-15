import { type Crop, type Hatch, paintPlate } from "./device";

/**
 * Display-only bilinear interpolation. Each output pixel is blended only when all
 * four contributing scientific pixels are valid. Otherwise the original exact
 * pixel rendering is retained, including hatches and transparent image edges.
 * The source array is never modified; science calculations never use this output.
 */
export function paintPlateSmooth(
  rgba: Uint8ClampedArray,
  noData: Uint8Array | null,
  nx: number,
  ny: number,
  k: number,
  crop: Crop,
  hatch: Hatch,
): Uint8ClampedArray<ArrayBuffer> {
  const out = paintPlate(rgba, noData, nx, ny, k, crop, hatch);
  if (k === 1) return out;
  const side = crop.size * k;
  for (let y = 0; y < side; y++) {
    const sourceY = crop.y0 + (y + 0.5) / k - 0.5;
    const y0 = Math.floor(sourceY);
    const y1 = y0 + 1;
    if (y0 < 0 || y1 >= ny) continue;
    const fy = sourceY - y0;
    for (let x = 0; x < side; x++) {
      const sourceX = crop.x0 + (x + 0.5) / k - 0.5;
      const x0 = Math.floor(sourceX);
      const x1 = x0 + 1;
      if (x0 < 0 || x1 >= nx) continue;
      const ids = [y0 * nx + x0, y0 * nx + x1, y1 * nx + x0, y1 * nx + x1];
      if (ids.some((id) => (noData !== null && noData[id] === 1) || rgba[id * 4 + 3] !== 255)) {
        continue;
      }
      const fx = sourceX - x0;
      const weights = [(1 - fx) * (1 - fy), fx * (1 - fy), (1 - fx) * fy, fx * fy];
      const dest = (y * side + x) * 4;
      for (let channel = 0; channel < 3; channel++) {
        out[dest + channel] = ids.reduce(
          (sum, id, index) => sum + rgba[id * 4 + channel] * weights[index],
          0,
        );
      }
      out[dest + 3] = 255;
    }
  }
  return out;
}
