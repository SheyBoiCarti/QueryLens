/**
 * Result cell comparators for exact numeric precision and stable sorting (Contract C09).
 */

export function compareDecimalStrings(a: string, b: string): number {
  const parseNumParts = (s: string) => {
    let sign = 1;
    let str = s.trim();
    if (str.startsWith('-')) {
      sign = -1;
      str = str.substring(1);
    } else if (str.startsWith('+')) {
      str = str.substring(1);
    }
    const [intPart = '0', fracPart = ''] = str.split('.');
    return { sign, intPart: intPart.replace(/^0+(?=\d)/, '') || '0', fracPart };
  };

  const pa = parseNumParts(a);
  const pb = parseNumParts(b);

  if (pa.sign !== pb.sign) {
    return pa.sign > pb.sign ? 1 : -1;
  }

  // Same sign
  const compareMagnitude = () => {
    if (pa.intPart.length !== pb.intPart.length) {
      return pa.intPart.length > pb.intPart.length ? 1 : -1;
    }
    if (pa.intPart !== pb.intPart) {
      return pa.intPart > pb.intPart ? 1 : -1;
    }
    const maxFracLen = Math.max(pa.fracPart.length, pb.fracPart.length);
    const fa = pa.fracPart.padEnd(maxFracLen, '0');
    const fb = pb.fracPart.padEnd(maxFracLen, '0');
    if (fa !== fb) {
      return fa > fb ? 1 : -1;
    }
    return 0;
  };

  const mag = compareMagnitude();
  return pa.sign === 1 ? mag : -mag;
}

export function compareCell(a: unknown, b: unknown, columnType: string = 'string'): number {
  if (a === null || a === undefined) {
    if (b === null || b === undefined) return 0;
    return 1; // null sorts last stably
  }
  if (b === null || b === undefined) {
    return -1;
  }

  if (columnType === 'integer' || columnType === 'decimal') {
    return compareDecimalStrings(String(a), String(b));
  }

  if (columnType === 'float') {
    const na = Number(a);
    const nb = Number(b);
    return na === nb ? 0 : na > nb ? 1 : -1;
  }

  if (columnType === 'boolean') {
    const ba = Boolean(a);
    const bb = Boolean(b);
    return ba === bb ? 0 : ba ? 1 : -1;
  }

  // Text preservation: preserve '001' vs '1' as text
  return String(a).localeCompare(String(b));
}
