import {describe,expect,it} from 'vitest';
import {clock,compass,defaults,parseGPX,parsePlan,toGPX,validPreferences,type Point} from './lib';

const points:Point[]=[[9.55,62.64],[9.56,62.645],[9.5701,62.6502]];

describe('GPX',()=>{
 it('round-trips points',()=>{expect(parseGPX(toGPX(points))).toEqual(points);});
 it('accepts rtept routes',()=>{expect(parseGPX('<gpx><rte><rtept lat="62.64" lon="9.55"/><rtept lat="62.65" lon="9.56"/></rte></gpx>')).toEqual([[9.55,62.64],[9.56,62.65]]);});
 it('takes the Up track from a Rando tour file',()=>{
  const gpx='<gpx><trk><name>Up · X</name><trkseg><trkpt lat="62.64" lon="9.55"/><trkpt lat="62.65" lon="9.56"/></trkseg></trk><trk><name>Down · X</name><trkseg><trkpt lat="62.65" lon="9.56"/><trkpt lat="62.66" lon="9.57"/></trkseg></trk></gpx>';
  expect(parseGPX(gpx)).toEqual([[9.55,62.64],[9.56,62.65]]);
  expect(()=>parseGPX(gpx.replace('Up · X','A'))).toThrow(/several tracks/);
 });
 it('rejects multi-segment tracks',()=>{expect(()=>parseGPX('<gpx><trk><trkseg><trkpt lat="62.64" lon="9.55"/></trkseg><trkseg><trkpt lat="62.65" lon="9.56"/></trkseg></trk></gpx>')).toThrow(/single continuous/);});
 it('rejects points outside the pilot area and malformed XML',()=>{
  expect(()=>parseGPX('<gpx><trk><trkseg><trkpt lat="59.9" lon="10.7"/><trkpt lat="59.95" lon="10.8"/></trkseg></trk></gpx>')).toThrow(/within the Trondheim pilot/);
  expect(()=>parseGPX('<gpx><trk>')).toThrow(/not a valid GPX/);
  expect(()=>parseGPX('<gpx><trk><trkseg><trkpt lat="62.64" lon="9.55"/></trkseg></trk></gpx>')).toThrow();
 });
});

describe('preferences and plans',()=>{
 it('validates defaults and rejects inverted ranges',()=>{
  expect(validPreferences(defaults)).toBe(true);
  expect(validPreferences({...defaults,lower:30,upper:20})).toBe(false);
  expect(validPreferences({...defaults,start:15,end:9})).toBe(false);
  expect(validPreferences({...defaults,mode:'bright'})).toBe(false);
  expect(validPreferences(null)).toBe(false);
 });
 it('parses plan files and rejects other versions',()=>{
  const plan={version:1,name:'Storhornet',preferences:defaults,points,center:[9.55,62.64]};
  expect(parsePlan(JSON.stringify(plan))).toEqual(plan);
  expect(()=>parsePlan(JSON.stringify({...plan,version:2}))).toThrow(/unsupported/);
  expect(()=>parsePlan(JSON.stringify({...plan,points:[[1,2]]}))).toThrow();
 });
});

describe('formatting',()=>{
 it('formats clocks and compass points',()=>{
  expect(clock(9.5)).toBe('09:30');expect(clock(23+5/6)).toBe('23:50');
  expect(compass(0)).toBe('N');expect(compass(359)).toBe('N');expect(compass(180)).toBe('S');expect(compass(null)).toBe('Unknown');
 });
});
