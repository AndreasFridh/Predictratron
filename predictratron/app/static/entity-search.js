/* Matching is literal except for * (any characters) and ? (one character). */
const EntitySearch = {
  matches(entity, query) {
    const text = String(query || '').trim().toLocaleLowerCase('sv-SE');
    const fields = [entity.entity_id, entity.name].map(value => String(value || '').toLocaleLowerCase('sv-SE'));
    if (!text) return true;
    if (!/[?*]/.test(text)) return fields.some(value => value.includes(text));
    return fields.some(value => {
      const pattern = Array.from(text), chars = Array.from(value);
      let p = 0, v = 0, star = -1, retry = 0;
      while (v < chars.length) {
        if (p < pattern.length && (pattern[p] === '?' || pattern[p] === chars[v])) {p++; v++;}
        else if (pattern[p] === '*') {star = p++; retry = v;}
        else if (star >= 0) {p = star + 1; v = ++retry;}
        else return false;
      }
      while (pattern[p] === '*') p++;
      return p === pattern.length;
    });
  },
  type(entity) { return entity.entity_id.startsWith('binary_sensor.') ? 'bool' : 'float'; },
  usable(entity) {
    if (this.type(entity) === 'bool') return true;
    if (['unknown', 'unavailable'].includes(entity.state)) return true;
    return String(entity.state ?? '').trim() !== '' && Number.isFinite(Number(entity.state));
  },
  value(entity) {
    if (entity.state === 'unavailable') return 'Otillgänglig';
    if (entity.state === 'unknown' || entity.state == null) return 'Okänt värde';
    if (entity.state === 'on') return 'På · 1';
    if (entity.state === 'off') return 'Av · 0';
    const number = Number(entity.state);
    const value = String(entity.state).trim() !== '' && Number.isFinite(number)
      ? number.toLocaleString('sv-SE', {maximumFractionDigits: 6}) : String(entity.state);
    return value + (entity.unit ? ' ' + entity.unit : '');
  },
  filter(entities, query, domain = '', numericOnly = false) {
    return entities.filter(entity => (!domain || entity.entity_id.startsWith(domain + '.')) &&
      (!numericOnly || this.usable(entity)) && this.matches(entity, query))
      .sort((a, b) => String(a.name || a.entity_id).localeCompare(String(b.name || b.entity_id), 'sv-SE') || a.entity_id.localeCompare(b.entity_id));
  }
};
if (typeof module !== 'undefined') module.exports = EntitySearch;
