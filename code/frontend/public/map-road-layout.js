/* Deterministic road geometry. Dependency data is never modified. */
(function (root) {
  const TAU = Math.PI * 2;
  function ports(edges, positions) {
    const junctions = new Map();
    edges.forEach(([a,b]) => {
      for (const [id,other] of [[a,b],[b,a]]) {
        const p=positions.get(id),q=positions.get(other);
        if(!junctions.has(id))junctions.set(id,[]);
        junctions.get(id).push({key:a+'>'+b, angle:(Math.atan2(q.y-p.y,q.x-p.x)+TAU)%TAU});
      }
    });
    const result = new Map();
    junctions.forEach((items,id) => {
      items.sort((a,b)=>a.angle-b.angle);
      let cut=0,gap=-1;
      items.forEach((item,i)=>{const next=items[(i+1)%items.length].angle+(i===items.length-1?TAU:0);if(next-item.angle>gap){gap=next-item.angle;cut=(i+1)%items.length}});
      const ordered=items.slice(cut).concat(items.slice(0,cut));
      const angles=ordered.map((item,i)=>item.angle+(i && item.angle<ordered[0].angle?TAU:0));
      const minimum=Math.min(Math.PI/9,TAU/(items.length+1));
      const adjusted=[...angles];
      for(let i=1;i<adjusted.length;i++)adjusted[i]=Math.max(adjusted[i],adjusted[i-1]+minimum);
      const shift=adjusted.reduce((sum,a,i)=>sum+a-angles[i],0)/adjusted.length;
      ordered.forEach((item,i)=>result.set(id+'|'+item.key,adjusted[i]-shift));
    });
    return result;
  }
  function curve(a,b,positions,angles) {
    const key=a+'>'+b,p=positions.get(a),q=positions.get(b);
    const start=angles.get(a+'|'+key),end=angles.get(b+'|'+key);
    const length=Math.hypot(q.x-p.x,q.y-p.y),radius=Math.min(8,length*.04),handle=Math.min(160,length*.32);
    const p0={x:p.x+Math.cos(start)*radius,y:p.y+Math.sin(start)*radius};
    const p1={x:p.x+Math.cos(start)*handle,y:p.y+Math.sin(start)*handle};
    const p2={x:q.x+Math.cos(end)*handle,y:q.y+Math.sin(end)*handle};
    const p3={x:q.x+Math.cos(end)*radius,y:q.y+Math.sin(end)*radius};
    const points=[];
    for(let i=0;i<=64;i++){const t=i/64,u=1-t;points.push({x:u*u*u*p0.x+3*u*u*t*p1.x+3*u*t*t*p2.x+t*t*t*p3.x,y:u*u*u*p0.y+3*u*u*t*p1.y+3*u*t*t*p2.y+t*t*t*p3.y})}
    return points;
  }
  const orientation=(a,b,c)=>(b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x);
  function crosses(a,b) {
    for(let i=1;i<a.length;i++)for(let j=1;j<b.length;j++){
      if(orientation(a[i-1],a[i],b[j-1])*orientation(a[i-1],a[i],b[j])<0 && orientation(b[j-1],b[j],a[i-1])*orientation(b[j-1],b[j],a[i])<0)return true;
    }
    return false;
  }
  function build(edges,positions,{avoidCrossings=true}={}) {
    const angles=ports(edges,positions),routes=new Map(),hidden=[];
    edges.forEach(([a,b])=>{
      const points=curve(a,b,positions,angles);
      if(avoidCrossings && [...routes.values()].some(other=>crosses(points,other))){hidden.push([a,b]);return}
      routes.set(a+'>'+b,points);
    });
    return {routes,hidden};
  }
  root.MapRoadLayout={build,crosses,ports};
})(globalThis);
