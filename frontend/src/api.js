export const account=()=>JSON.parse(localStorage.getItem('apiary-account')||'null');
export const loginAs=x=>localStorage.setItem('apiary-account',JSON.stringify(x));
export function reason(detail){
  if(detail==null)return '请求未能完成';
  if(typeof detail==='string')return detail;
  if(Array.isArray(detail))return detail.map(d=>d.msg?`${(d.loc||[]).slice(1).join('.')}：${d.msg}`:reason(d)).join('；');
  if(typeof detail==='object'){
    const lines=[detail.message||detail.msg||'请求未能完成'];
    for(const key of ['issues','missing','incomplete','conflicts','care']){
      if(Array.isArray(detail[key])&&detail[key].length){
        lines.push(detail[key].map(item=>[item.hive_code||item.code||(item.care_id?'CARE-'+item.care_id:''),item.missing_fields?.length?'缺'+item.missing_fields.join('、'):'',item.reason||item.conflict_note||item.status||''].filter(Boolean).join(' · ')).join('；'));
      }
    }
    return lines.join('\n');
  }
  return String(detail);
}
export async function api(path,method='GET',body){const response=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json',...(account()?{Authorization:'Bearer '+account().token}:{})},body:body?JSON.stringify(body):undefined});const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(reason(data.detail)||`请求失败（${response.status}）`);return data;}
