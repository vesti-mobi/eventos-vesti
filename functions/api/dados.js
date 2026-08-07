// GET /api/dados — presença (HubSpot) + custos (planilha). Mesma resposta do servidor.py.
import { buildDados, withCache } from "./_shared.js";

export function onRequestGet(context) {
  return withCache(context, 180, () => buildDados(context.env)); // cache de 3 min
}
