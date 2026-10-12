class EntityPicker {
  constructor() {
    this.entities = []; this.configured = false; this.loading = false;
    this.onSelect = null; this.allowBoolean = true; this.limit = 50; this.error = '';
    $('close-entity-picker').onclick = () => $('entity-picker').close();
    $('entity-query').oninput = () => {this.limit = 50; this.render();};
    $('entity-domain').onchange = () => {this.limit = 50; this.render();};
    $('entity-numeric').onchange = () => {this.limit = 50; this.render();};
    $('refresh-entities').onclick = () => this.refresh();
    $('entity-more').onclick = () => {this.limit += 50; this.render();};
    document.addEventListener('click', event => {
      const button = event.target.closest('[data-entity-picker]');
      if (!button) return;
      const input = button.previousElementSibling;
      if (input.disabled) return;
      const signalForm = input.closest('#signal-form');
      const output = input.name === 'target_entity' || (signalForm && $('signal-role').textContent === 'OUTPUT SIGNAL');
      this.open(input.value, entity => {
        input.value = entity.entity_id;
        if (signalForm) {
          signalForm.elements.label.value = entity.name || entity.entity_id;
          signalForm.elements.data_type.value = EntitySearch.type(entity);
          if (EntitySearch.type(entity) === 'bool') signalForm.elements.statistic.value = 'last';
        }
        input.dispatchEvent(new Event('change', {bubbles:true}));
      }, !output);
    });
  }
  setEntities(entities) {
    this.entities = entities; this.error = ''; this.fetched = new Date();
    window.flowEditor?.setEntities(entities);
    $('ha-entity-count').textContent = `${entities.length} signals · search and select`;
    this.render();
  }
  setConfigured(configured) {this.configured = configured; this.render();}
  async refresh() {
    if (this.loading || !this.configured) return;
    this.loading = true; this.error = ''; this.render();
    try {this.setEntities(await api('entities'));}
    catch (error) {this.error = error.message;}
    finally {this.loading = false; this.render();}
  }
  open(query, onSelect, allowBoolean = true) {
    this.onSelect = onSelect; this.allowBoolean = allowBoolean; this.limit = 50;
    $('entity-query').value = query || ''; $('entity-domain').value = ''; $('entity-numeric').checked = false;
    $('entity-picker').showModal(); this.render(); $('entity-query').focus();
    if (this.configured) this.refresh();
  }
  render() {
    $('refresh-entities').disabled = this.loading || !this.configured;
    $('entity-more').hidden = true;
    const results = $('entity-results');
    if (!this.configured) {
      $('entity-count').textContent = 'Home Assistant is not connected.';
      results.innerHTML = '<p class="entity-empty">Connect Home Assistant to search your signals. You can still enter an entity ID in signal settings.</p>'; return;
    }
    const matches = EntitySearch.filter(this.entities, $('entity-query').value, $('entity-domain').value, $('entity-numeric').checked);
    const shown = matches.slice(0, this.limit);
    $('entity-count').textContent = this.error ? `Could not refresh: ${this.error}` : this.loading ? 'Fetching latest values…' :
      `${matches.length} of ${this.entities.length} signals · showing ${shown.length}` + (this.fetched ? ` · fetched ${this.fetched.toLocaleTimeString('en-GB')}` : '');
    $('entity-more').hidden = matches.length <= this.limit;
    results.innerHTML = shown.map(entity => {
      const usable = EntitySearch.usable(entity), boolean = EntitySearch.type(entity) === 'bool';
      const disabled = !usable || (boolean && !this.allowBoolean);
      const reason = !usable ? 'Text value · cannot be used in ML' : boolean && !this.allowBoolean ? 'Boolean signals can only be inputs' : '';
      const stamp = entity.last_updated ? new Date(entity.last_updated) : null;
      const updated = stamp && !Number.isNaN(stamp.valueOf()) ? stamp.toLocaleString('en-GB') : 'Time unavailable';
      return `<button type="button" class="entity-result" data-entity-id="${esc(entity.entity_id)}" ${disabled?'disabled':''} aria-label="Select ${esc(entity.name)} (${esc(entity.entity_id)})"><span class="entity-name">○ – ${esc(entity.name)} <small>(${boolean?'Boolean':'Float'})</small></span><strong class="entity-value">${esc(EntitySearch.value(entity))}</strong><code>${esc(entity.entity_id)}</code><span class="entity-updated">Updated ${esc(updated)}</span>${reason?`<span class="entity-reason">${esc(reason)}</span>`:''}</button>`;
    }).join('') || `<p class="entity-empty">${this.loading?'Fetching signals…':this.error?'Try refreshing again.':'No matching signals. Try sensor.*temp* or change the filter.'}</p>`;
    results.querySelectorAll('[data-entity-id]').forEach(button => {
      button.onclick = () => {
        const entity = this.entities.find(item => item.entity_id === button.dataset.entityId);
        if (!entity || button.disabled) return;
        this.onSelect?.(entity); $('entity-picker').close();
      };
    });
  }
}
window.entityPicker = new EntityPicker();
