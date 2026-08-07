// GET /api/satisfacao — respostas do formulário de satisfação (planilha).
import { fetchSatisfacao, withCache } from "./_shared.js";

export function onRequestGet(context) {
  return withCache(context, 180, () => fetchSatisfacao(context.env)); // cache de 3 min
}
