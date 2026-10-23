// Where the sun and moon are in the sky, for the sky backdrop (DESIGN §10.1).
// Standard low-precision formulas (about a degree), plenty for a picture.
// Angles in degrees; azimuth is measured from north through east.

const RAD = Math.PI / 180;
const OBLIQUITY = 23.4397 * RAD;

// Days since 2000-01-01 12:00 UTC (J2000).
const daysSinceJ2000 = (date) => date.getTime() / 86400000 - 10957.5;

function equatorial(lon, lat) {
  return {
    ra: Math.atan2(Math.sin(lon) * Math.cos(OBLIQUITY) - Math.tan(lat) * Math.sin(OBLIQUITY), Math.cos(lon)),
    dec: Math.asin(Math.sin(lat) * Math.cos(OBLIQUITY) + Math.cos(lat) * Math.sin(OBLIQUITY) * Math.sin(lon)),
  };
}

function horizontal({ ra, dec }, d, latDeg, lonDeg) {
  const phi = latDeg * RAD;
  const hourAngle = (280.16 + 360.9856235 * d) * RAD + lonDeg * RAD - ra;
  const alt = Math.asin(Math.sin(phi) * Math.sin(dec) + Math.cos(phi) * Math.cos(dec) * Math.cos(hourAngle));
  // From south, positive westwards, then turned to "from north, through east".
  const azSouth = Math.atan2(Math.sin(hourAngle), Math.cos(hourAngle) * Math.sin(phi) - Math.tan(dec) * Math.cos(phi));
  return { alt: alt / RAD, az: ((azSouth / RAD + 180) % 360 + 360) % 360 };
}

function sunEcliptic(d) {
  const m = (357.5291 + 0.98560028 * d) * RAD;
  const c = (1.9148 * Math.sin(m) + 0.02 * Math.sin(2 * m) + 0.0003 * Math.sin(3 * m)) * RAD;
  return m + c + (102.9372 + 180) * RAD;  // ecliptic longitude; latitude 0
}

function moonEcliptic(d) {
  const l = (218.316 + 13.176396 * d) * RAD;  // mean longitude
  const m = (134.963 + 13.064993 * d) * RAD;  // mean anomaly
  const f = (93.272 + 13.22935 * d) * RAD;    // mean distance from the node
  return { lon: l + 6.289 * RAD * Math.sin(m), lat: 5.128 * RAD * Math.sin(f) };
}

export function sunEquatorial(date) {
  return equatorial(sunEcliptic(daysSinceJ2000(date)), 0);
}

export function moonEquatorial(date) {
  const { lon, lat } = moonEcliptic(daysSinceJ2000(date));
  return equatorial(lon, lat);
}

export function sunPosition(date, lat, lon) {
  const d = daysSinceJ2000(date);
  return horizontal(equatorial(sunEcliptic(d), 0), d, lat, lon);
}

export function moonPosition(date, lat, lon) {
  const d = daysSinceJ2000(date);
  const { lon: ml, lat: mb } = moonEcliptic(d);
  return horizontal(equatorial(ml, mb), d, lat, lon);
}

// The moon's phase: 0 new, 0.25 first quarter, 0.5 full, 0.75 last quarter.
// lit: the fraction of the disc that is lit.
export function moonPhase(date) {
  const d = daysSinceJ2000(date);
  const elongation = moonEcliptic(d).lon - sunEcliptic(d);
  const phase = ((elongation / (2 * Math.PI)) % 1 + 1) % 1;
  return { phase, lit: (1 - Math.cos(2 * Math.PI * phase)) / 2 };
}
