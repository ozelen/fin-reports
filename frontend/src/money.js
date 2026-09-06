const UAH_SIGN = "\u20B4";

export function money(v, code, empty = "—") {
  if (v == null || v === "") return empty;
  const ccy = (code || "EUR").toUpperCase();
  const n = Number(v);
  if (ccy === "UAH") {
    return `${new Intl.NumberFormat("es-ES", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n)} ${UAH_SIGN}`;
  }
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: ccy,
  }).format(n);
}
