// Minimal GRIB decoder for gridded reanalysis fields (ERA5-Land from the
// Climate Data Store): editions 1 and 2, regular latitude / longitude grids,
// simple packing, with or without a bitmap. Enough for the website's CDS
// layers; anything else throws, so the map can say so.

// #region grib-decode
/**
 * Decode every message of a GRIB file (ArrayBuffer). Each message:
 * {time: Date (valid time), ni, nj, west, north, di, dj (degrees, cell
 *  spacing), values: Float32Array (nj rows from north to south, ni columns
 *  from west to east; NaN = missing)}.
 */
export function decodeGrib(buffer) {
  const bytes = new Uint8Array(buffer);
  const out = [];
  let pos = 0;
  while (pos < bytes.length - 8) {
    // Find the next "GRIB" (files may have padding between messages).
    if (!(bytes[pos] === 0x47 && bytes[pos + 1] === 0x52 && bytes[pos + 2] === 0x49 && bytes[pos + 3] === 0x42)) {
      pos++;
      continue;
    }
    const edition = bytes[pos + 7];
    if (edition === 1) {
      const len = u24(bytes, pos + 4);
      out.push(grib1(bytes, pos));
      pos += len;
    } else if (edition === 2) {
      const len = Number(new DataView(buffer, pos + 8, 8).getBigUint64(0));
      out.push(...grib2(bytes, pos, len));
      pos += len;
    } else {
      throw new Error(`GRIB edition ${edition} is not supported`);
    }
  }
  return out;
}
// #endregion grib-decode

const u16 = (b, i) => (b[i] << 8) | b[i + 1];
const u24 = (b, i) => (b[i] << 16) | (b[i + 1] << 8) | b[i + 2];
const u32 = (b, i) => ((b[i] << 24) >>> 0) + ((b[i + 1] << 16) | (b[i + 2] << 8) | b[i + 3]);
/** Sign-and-magnitude integers (GRIB's signed numbers). */
const s16 = (b, i) => (b[i] & 0x80 ? -1 : 1) * (((b[i] & 0x7f) << 8) | b[i + 1]);
const s24 = (b, i) => (b[i] & 0x80 ? -1 : 1) * (((b[i] & 0x7f) << 16) | (b[i + 1] << 8) | b[i + 2]);
const s32 = (b, i) => (b[i] & 0x80 ? -1 : 1) * (((b[i] & 0x7f) * 2 ** 24) + ((b[i + 1] << 16) | (b[i + 2] << 8) | b[i + 3]));

/** IBM single-precision float (GRIB 1 reference values). */
function ibm(b, i) {
  const sign = b[i] & 0x80 ? -1 : 1;
  const exp = (b[i] & 0x7f) - 64;
  const mant = u24(b, i + 1) / 2 ** 24;
  return sign * mant * 16 ** exp;
}

/** Unpack n values of `bits` bits each from a bit stream starting at byte `start`. */
function unpack(b, start, n, bits) {
  const out = new Float64Array(n);
  if (bits === 0) return out;
  let bitPos = start * 8;
  for (let k = 0; k < n; k++) {
    let v = 0;
    let need = bits;
    while (need > 0) {
      const byte = b[bitPos >> 3];
      const off = bitPos & 7;
      const take = Math.min(8 - off, need);
      v = v * 2 ** take + ((byte >> (8 - off - take)) & ((1 << take) - 1));
      bitPos += take;
      need -= take;
    }
    out[k] = v;
  }
  return out;
}

/** Values on the grid from packed values and an optional bitmap (bits from byte `bitmapStart`). */
function expand(packed, npoints, bitmap, b, ref, binScale, decScale) {
  const values = new Float32Array(npoints);
  const e = 2 ** binScale;
  const d = 10 ** -decScale;
  let k = 0;
  for (let i = 0; i < npoints; i++) {
    if (bitmap != null && !((b[bitmap + (i >> 3)] >> (7 - (i & 7))) & 1)) {
      values[i] = NaN;
      continue;
    }
    values[i] = (ref + packed[k++] * e) * d;
  }
  return values;
}

/** Reorder to rows north -> south, columns west -> east (from GRIB's scanning mode flags). */
function orient(msg, scan) {
  const { ni, nj, values } = msg;
  if (scan & 0x20) throw new Error("GRIB: column-major scanning is not supported");
  const flipI = !!(scan & 0x80);
  const flipJ = !!(scan & 0x40); // rows from south to north
  if (flipI || flipJ) {
    const v = new Float32Array(values.length);
    for (let j = 0; j < nj; j++)
      for (let i = 0; i < ni; i++) v[j * ni + i] = values[(flipJ ? nj - 1 - j : j) * ni + (flipI ? ni - 1 - i : i)];
    msg.values = v;
  }
  return msg;
}

/** Longitude in [-180, 180). */
const wrapLon = (lon) => ((((lon + 180) % 360) + 360) % 360) - 180;

function grid(lat1, lon1, lat2, lon2, di, dj, ni, nj) {
  const north = Math.max(lat1, lat2);
  const west = wrapLon(Math.min(lon1, lon2 < lon1 ? lon2 + 360 : lon2));
  return { ni, nj, north, west, di: Math.abs(di), dj: Math.abs(dj) };
}

// #region grib1
function grib1(b, start) {
  let p = start + 8;
  const pds = p;
  const pdsLen = u24(b, pds);
  const hasGds = b[pds + 7] & 0x80;
  const hasBms = b[pds + 7] & 0x40;
  const year = (b[pds + 24] - 1) * 100 + b[pds + 12];
  const unit = b[pds + 17];
  const p1 = b[pds + 18];
  const hours = { 0: 1 / 60, 1: 1, 2: 24, 10: 3, 11: 6, 12: 12, 254: 1 / 3600 }[unit] ?? 1;
  const time = new Date(Date.UTC(year, b[pds + 13] - 1, b[pds + 14], b[pds + 15], b[pds + 16]) + (b[pds + 20] <= 1 ? p1 * hours * 3600e3 : 0));
  const decScale = s16(b, pds + 26);
  p += pdsLen;
  if (!hasGds) throw new Error("GRIB 1: no grid description");
  const gds = p;
  if (b[gds + 5] !== 0) throw new Error(`GRIB 1: grid type ${b[gds + 5]} is not a regular lat/lon grid`);
  const ni = u16(b, gds + 6);
  const nj = u16(b, gds + 8);
  const g = grid(s24(b, gds + 10) / 1000, s24(b, gds + 13) / 1000, s24(b, gds + 17) / 1000, s24(b, gds + 20) / 1000, u16(b, gds + 23) / 1000, u16(b, gds + 25) / 1000, ni, nj);
  const scan = b[gds + 27];
  p += u24(b, gds);
  let bitmap = null;
  if (hasBms) {
    if (u16(b, p + 4) !== 0) throw new Error("GRIB 1: predefined bitmaps are not supported");
    bitmap = p + 6;
    p += u24(b, p);
  }
  const bds = p;
  const flag = b[bds + 3];
  if (flag & 0xc0) throw new Error("GRIB 1: only simple packing of grid point data is supported");
  const binScale = s16(b, bds + 4);
  const ref = ibm(b, bds + 6);
  const bits = b[bds + 10];
  const npoints = ni * nj;
  let n = npoints;
  if (bitmap != null) {
    n = 0;
    for (let i = 0; i < npoints; i++) n += (b[bitmap + (i >> 3)] >> (7 - (i & 7))) & 1;
  }
  const packed = unpack(b, bds + 11, n, bits);
  return orient({ time, ...g, values: expand(packed, npoints, bitmap, b, ref, binScale, decScale) }, scan);
}
// #endregion grib1

// #region grib2
function grib2(b, start, len) {
  const view = new DataView(b.buffer, b.byteOffset);
  const end = start + len - 4;
  let p = start + 16;
  let ref = null;
  let g = null;
  let scan = 0;
  let pack = null;
  let bitmap = null;
  let forecast = 0;
  const out = [];
  while (p < end) {
    const secLen = u32(b, p);
    const num = b[p + 4];
    if (num === 1) {
      ref = Date.UTC(u16(b, p + 12), b[p + 14] - 1, b[p + 15], b[p + 16], b[p + 17], b[p + 18]);
    } else if (num === 3) {
      const tpl = u16(b, p + 12);
      if (tpl !== 0) throw new Error(`GRIB 2: grid template ${tpl} is not a regular lat/lon grid`);
      const ni = u32(b, p + 30);
      const nj = u32(b, p + 34);
      const basic = u32(b, p + 38);
      const sub = u32(b, p + 42);
      const unit = basic && sub && basic !== 0xffffffff ? basic / sub : 1e-6;
      g = grid(s32(b, p + 46) * unit, s32(b, p + 50) * unit, s32(b, p + 55) * unit, s32(b, p + 59) * unit, u32(b, p + 63) * unit, u32(b, p + 67) * unit, ni, nj);
      scan = b[p + 71];
    } else if (num === 4) {
      const tpl = u16(b, p + 7);
      if (tpl === 0 || tpl === 1 || tpl === 8) {
        const unit = b[p + 17];
        const hours = { 0: 1 / 60, 1: 1, 2: 24, 10: 3, 11: 6, 12: 12, 13: 1 / 3600 }[unit] ?? 1;
        forecast = s32(b, p + 18) * hours * 3600e3;
      }
    } else if (num === 5) {
      const tpl = u16(b, p + 9);
      if (tpl !== 0) throw new Error(`GRIB 2: data template 5.${tpl} is not supported (only simple packing)`);
      pack = { n: u32(b, p + 5), ref: view.getFloat32(p + 11), binScale: s16(b, p + 15), decScale: s16(b, p + 17), bits: b[p + 19] };
    } else if (num === 6) {
      const ind = b[p + 5];
      if (ind === 0) bitmap = p + 6;
      else if (ind !== 255 && ind !== 254) throw new Error("GRIB 2: predefined bitmaps are not supported");
      if (ind === 255) bitmap = null;
    } else if (num === 7) {
      if (!g || !pack) throw new Error("GRIB 2: data before grid / packing sections");
      const packed = unpack(b, p + 5, pack.n, pack.bits);
      const values = expand(packed, g.ni * g.nj, bitmap, b, pack.ref, pack.binScale, pack.decScale);
      out.push(orient({ time: new Date(ref + forecast), ...g, values }, scan));
    }
    p += secLen;
  }
  return out;
}
// #endregion grib2
