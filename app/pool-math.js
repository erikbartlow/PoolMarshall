/* Independent pool-planning arithmetic. No proprietary Pooli code or models. */
(function(root){
'use strict';
const number=(v,name,min=-Infinity,max=Infinity)=>{if(v===''||v===null||v===undefined||!Number.isFinite(Number(v))||Number(v)<min||Number(v)>max)throw Error('Enter a valid '+name);return Number(v)};
function volume(shape,l,w,shallow,deep){l=number(l,'length',.01);w=number(w,'width',.01);shallow=number(shallow,'shallow depth',.01);deep=number(deep,'deep depth',shallow);return l*w*(shallow+deep)/2*(shape==='oval'?Math.PI/4:1)*7.48051948}
function dilution(current,source,fraction){return number(current,'current concentration',0)*(1-number(fraction,'replacement fraction',0,1))+number(source,'source concentration',0)*fraction}
function dryDose(gallons,current,target,purity){const delta=number(target,'target ppm',0)-number(current,'current ppm',0);if(delta<0)throw Error('This addition calculator only raises concentration. Use replacement planning for reduction.');return delta*number(gallons,'pool gallons',1)*3.785411784/1000/(number(purity,'active strength percent',.01,100)/100)}
function labelDose(gallons,change,amount,labelGallons,labelChange){return number(gallons,'pool gallons',1)/number(labelGallons,'label gallons',1)*number(change,'desired ppm rise',0)/number(labelChange,'label ppm rise',.001)*number(amount,'label amount',.001)}
function lsi(ph,tempF,calcium,carbonate,tds){ph=number(ph,'pH',6,9);const c=(number(tempF,'water temperature',32,110)-32)*5/9;calcium=number(calcium,'calcium hardness',1);carbonate=number(carbonate,'carbonate alkalinity',1);tds=number(tds,'measured TDS',1);const A=(Math.log10(tds)-1)/10,B=-13.12*Math.log10(c+273)+34.55,C=Math.log10(calcium)-.4,D=Math.log10(carbonate);return ph-((9.3+A+B)-(C+D))}
function carbonate(ta,cya,ph){ta=number(ta,'total alkalinity',0);cya=number(cya,'CYA',0);ph=number(ph,'pH',7,8);const table=[[7,.23],[7.2,.27],[7.4,.31],[7.6,.33],[7.8,.35],[8,.36]];let factor=.36;for(let i=1;i<table.length;i++){if(ph<=table[i][0]){const [x,y]=table[i-1],[x1,y1]=table[i];factor=y+(y1-y)*(ph-x)/(x1-x);break;}}return ta-cya*factor}
function meter(previous,current,hours){return (number(current,'current meter',0)-number(previous,'previous meter',0))/number(hours,'elapsed hours',.001)*24}
const api={number,volume,dilution,dryDose,labelDose,lsi,carbonate,meter};root.PoolMath=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
