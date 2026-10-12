const {test} = require('node:test');
const assert = require('node:assert/strict');
const search = require('../../app/static/entity-search.js');
const entities = [
  {entity_id:'sensor.kitchen_temperature', name:'Temperatur kök', state:'21.75', unit:'°C'},
  {entity_id:'sensor.garden_temperature', name:'Temperatur ute', state:'unavailable', unit:'°C'},
  {entity_id:'sensor.energy', name:'Elförbrukning', state:'1.2', unit:'kWh'},
  {entity_id:'binary_sensor.rain', name:'Regn', state:'on'},
  {entity_id:'input_number.target', name:'Börvärde', state:'20'},
  {entity_id:'sensor.description', name:'Beskrivning', state:'soligt'},
];
test('plain search finds name or entity id, ignores case and whitespace', () => {
  assert.equal(search.filter(entities, '  KÖK ').length, 1);
  assert.equal(search.filter(entities, 'temperature').length, 2);
  assert.equal(search.filter(entities, '').length, 6);
});
test('wildcards match entire entity id or friendly name', () => {
  assert.equal(search.filter(entities, 'sensor.*temp*').length, 2);
  assert.equal(search.filter(entities, '*kök*').length, 1);
  assert.equal(search.filter(entities, 'sensor.energ?').length, 1);
  assert.equal(search.filter(entities, 'temp*').length, 2);
  assert.equal(search.filter(entities, 'sensor.temperatur*').length, 0);
});
test('regex metacharacters stay literal, not executable patterns', () => {
  for (const query of ['sensor.(energy|rain)*', 'sensor.[a-z]*', 'sensor.energy+*', '*\\*', '*(?=a)*']) {
    assert.equal(search.filter(entities, query).length, 0);
  }
  assert(search.matches({entity_id:'sensor.a+b', name:''}, '*a+b'));
});
test('type filters and model eligibility preserve unavailable historical sensors', () => {
  assert.equal(search.filter(entities, '*', 'sensor', true).length, 3);
  assert.equal(search.filter(entities, '', 'binary_sensor').length, 1);
  assert.equal(search.filter(entities, '', 'input_number').length, 1);
  assert(!search.usable({entity_id:'sensor.a',state:''}));
  assert(!search.usable({entity_id:'sensor.a',state:'NaN'}));
  assert(search.usable({entity_id:'sensor.a',state:'unknown'}));
});
test('latest values include units, boolean meaning and explicit unavailable states', () => {
  assert.equal(search.value(entities[0]), '21.75 °C');
  assert.equal(search.value(entities[1]), 'Unavailable');
  assert.equal(search.value(entities[3]), 'On · 1');
  assert.equal(search.value({state:'off'}), 'Off · 0');
  assert.equal(search.value({state:'unknown'}), 'Unknown value');
});

test('repeated stars and unicode question marks remain predictable', () => {
  assert(search.matches({name:'Kök 🌧',entity_id:''}, 'Kök ?'));
  assert(search.matches(entities[0], 'sensor.**kitchen**temperature'));
  assert(!search.matches({name:'a'.repeat(500),entity_id:''}, '*a'.repeat(30)+'b*'));
});
