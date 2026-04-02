'use strict';

// ═══════════════════════════════════════════════════════════════════
// XSS PROTECTION & HELPERS
// ═══════════════════════════════════════════════════════════════════
const ESC = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
function esc(str){ return String(str ?? '').replace(/[&<>"']/g, m=>ESC[m]); }
function setText(id, val){ const el=$(id); if(el) el.textContent=val; }
function $(id){ return document.getElementById(id); }
function ce(tag,attrs={},text=''){
  const e=document.createElement(tag);
  Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,v));
  if(text) e.textContent=text;
  return e;
}

// ═══════════════════════════════════════════════════════════════════
// API
// ═══════════════════════════════════════════════════════════════════
async function api(method,path,body){
  const opts={method,headers:{'Content-Type':'application/json'},credentials:'include'};
  if(body) opts.body=JSON.stringify(body);
  const res=await fetch('/api'+path,opts);
  const data=await res.json().catch(()=>({}));
  if(!res.ok) throw {status:res.status,message:data.error||'Ошибка сервера'};
  return data;
}
const GET   = p    => api('GET',p);
const POST  = (p,b)=> api('POST',p,b);
const PUT   = (p,b)=> api('PUT',p,b);
const PATCH = (p,b)=> api('PATCH',p,b);
const DEL   = p    => api('DELETE',p);

// ═══════════════════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════════════════
let state = {
  categories:[],menu:[],promos:[],reviews:[],cart:[],settings:{},
  currentUser:null, // {id, username, role, full_name, email, phone}
  favorites: new Set(JSON.parse(localStorage.getItem('sc_favs')||'[]')),
  activeFilter:'all',activeSort:'default',appliedPromo:null,
};
const ROLE_LABELS={client:'👤 Клиент',manager:'📋 Менеджер',admin:'⚙ Админ'};
let resetPassUserId=null;
let currentCheckoutStep=1, currentRating=0, pendingPhotoDataUrl=null, editingMenuId=null;

// ═══════════════════════════════════════════════════════════════════
// PHOTO FALLBACK MAP
// ═══════════════════════════════════════════════════════════════════
const PHOTO_MAP={
  'Пицца Маргарита':'https://images.unsplash.com/photo-1604382354936-07c5d9983bd3?w=600&q=80',
  'Пицца Пепперони':'https://images.unsplash.com/photo-1628840042765-356cda07504e?w=600&q=80',
  'Пицца 4 сыра':'https://images.unsplash.com/photo-1513104890138-7c749659a591?w=600&q=80',
  'Чизбургер':'https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=600&q=80',
  'Смоки Бургер':'https://images.unsplash.com/photo-1553979459-d2229ba7433b?w=600&q=80',
  'Гриль Бургер':'https://images.unsplash.com/photo-1586816001966-79b736744398?w=600&q=80',
  'Сет Калифорния':'https://images.unsplash.com/photo-1562802378-063ec186a863?w=600&q=80',
  'Лосось Ролл':'https://images.unsplash.com/photo-1553621042-f6e147245754?w=600&q=80',
  'Карбонара':'https://images.unsplash.com/photo-1612874742237-6526221588e3?w=600&q=80',
  'Болоньезе':'https://images.unsplash.com/photo-1555949258-eb67b1ef0ceb?w=600&q=80',
  'Греческий салат':'https://images.unsplash.com/photo-1540189549336-e6e99c3679fe?w=600&q=80',
  'Тирамису':'https://images.unsplash.com/photo-1571877227200-a0d98ea607e9?w=600&q=80',
};
function getPhoto(item){ return item.photo_url||PHOTO_MAP[item.name]||null; }

function renderImg(item,cls='menu-card-photo'){
  const photo=getPhoto(item);
  if(photo){
    const img=ce('img',{src:photo,alt:esc(item.name),loading:'lazy',class:cls});
    img.addEventListener('error',()=>{
      const w=document.createElement('div'); w.className='menu-card-emoji-wrap';
      w.textContent=item.emoji||'🍽'; img.replaceWith(w);
    });
    return img;
  }
  const w=document.createElement('div'); w.className='menu-card-emoji-wrap';
  w.textContent=item.emoji||'🍽'; return w;
}

// ═══════════════════════════════════════════════════════════════════
// SETTINGS
// ═══════════════════════════════════════════════════════════════════
function applySettings(s){
  if(!s) return;
  if(s.accent_color) document.documentElement.style.setProperty('--yellow',s.accent_color);
  if(s.dark_color)   document.documentElement.style.setProperty('--dark',s.dark_color);
  const heroTitle=$('heroTitle');
  if(heroTitle && s.hero_title){
    heroTitle.textContent=s.hero_title;
    heroTitle.insertAdjacentHTML('beforeend','<br>за <span class="accent" id="heroTime">'+esc(s.hero_time||'30 мин')+'</span>');
  }
  if(s.hero_sub)      setText('heroSub',s.hero_sub);
  if(s.stat_orders)   setText('statOrders',s.stat_orders);
  if(s.stat_partners) setText('statPartners',s.stat_partners);
  if(s.stat_rating)   setText('statRating',s.stat_rating);
  if(s.phone){
    setText('phone',s.phone);
    $('phone')?.closest('a')?.setAttribute('href','tel:'+s.phone.replace(/\D/g,''));
  }
  if(s.email){
    setText('email',s.email);
    $('email')?.closest('a')?.setAttribute('href','mailto:'+s.email);
  }
  if(s.address)     setText('address',s.address);
  if(s.hours)       { setText('hours',s.hours); checkOpenStatus(s.hours); }
  if(s.footer)      setText('footerText',s.footer);
  if(s.about_title) setText('aboutTitle',s.about_title);
  if(s.about_text)  setText('aboutText',s.about_text);
  if(s.promo_title) setText('promoTitle',s.promo_title);
  if(s.promo_desc)  setText('promoDesc',s.promo_desc);
  if(s.promo_banner_code) setText('promoCodeDisplay',s.promo_banner_code);
}

// FIX: correct open/closed badge check
function checkOpenStatus(hours){
  if(!hours) return;
  const m=hours.match(/(\d{1,2}):(\d{2}).*?(\d{1,2}):(\d{2})/);
  if(!m) return;
  const now=new Date();
  const cur=now.getHours()*60+now.getMinutes();
  const open=parseInt(m[1])*60+parseInt(m[2]);
  const close=parseInt(m[3])*60+parseInt(m[4]);
  const isOpen=cur>=open && cur<close;
  let badge=$('.open-status');
  if(!badge){
    badge=document.createElement('span');
    const navRight=$('navRight');
    if(navRight) navRight.prepend(badge);
  }
  badge.className='open-status '+(isOpen?'open':'closed');
  badge.innerHTML='<span>'+(isOpen?'Открыто':'Закрыто')+'</span>';
}

// ═══════════════════════════════════════════════════════════════════
// HITS
// ═══════════════════════════════════════════════════════════════════
function renderHits(){
  const container=$('hitsScroll'); container.innerHTML='';
  const hits=state.menu.filter(m=>m.badge==='хит').slice(0,8);
  if(!hits.length){ $('hits-section').style.display='none'; return; }
  $('hits-section').style.display='';
  hits.forEach(item=>{
    const card=document.createElement('div'); card.className='hit-card';
    card.setAttribute('role','listitem'); card.setAttribute('tabindex','0');
    card.setAttribute('aria-label',item.name+', '+item.price+' ₽');
    const imgWrap=document.createElement('div'); imgWrap.className='hit-img';
    imgWrap.appendChild(renderImg(item,'hit-card-photo'));
    const body=document.createElement('div'); body.className='hit-body';
    const name=ce('div',{class:'hit-name'}); name.textContent=item.name;
    const price=ce('div',{class:'hit-price'}); price.textContent=item.price+' ₽';
    body.append(name,price); card.append(imgWrap,body);
    card.addEventListener('click',()=>addToCart(item.id));
    card.addEventListener('keydown',e=>{ if(e.key==='Enter'||e.key===' ') addToCart(item.id); });
    container.appendChild(card);
  });
}

// ═══════════════════════════════════════════════════════════════════
// CATEGORIES
// ═══════════════════════════════════════════════════════════════════
function renderCategories(){
  const grid=$('catGrid'), filterBar=$('filterBar');
  grid.innerHTML='';
  filterBar.querySelectorAll('.filter-btn:not([data-cat="all"])').forEach(b=>b.remove());
  const dl=$('adm-catList');
  if(dl){ dl.innerHTML=''; state.categories.forEach(c=>{ const o=ce('option'); o.value=c.name; dl.appendChild(o); }); }
  state.categories.forEach(c=>{
    const card=document.createElement('div'); card.className='cat-card';
    card.setAttribute('role','listitem'); card.setAttribute('tabindex','0');
    card.setAttribute('aria-label','Категория '+c.name);
    const emoji=ce('div',{class:'cat-emoji'}); emoji.textContent=c.emoji||'🍽';
    const name=ce('div',{class:'cat-name'}); name.textContent=c.name;
    card.append(emoji,name);
    card.addEventListener('click',()=>filterMenu(c.name,card));
    card.addEventListener('keydown',e=>{ if(e.key==='Enter'||e.key===' ') filterMenu(c.name,card); });
    grid.appendChild(card);
    const btn=document.createElement('button'); btn.className='filter-btn'; btn.dataset.cat=c.name; btn.textContent=c.name;
    btn.addEventListener('click',()=>{
      document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active'); state.activeFilter=c.name; renderMenu();
    });
    filterBar.appendChild(btn);

    // Populate Mobile Menu Level 2
    const mLi = document.createElement('li');
    const mLink = ce('a', { href: '#menu-section' }, c.emoji + ' ' + c.name);
    mLink.onclick = () => { filterMenu(c.name); closeMenu(); };
    mLi.appendChild(mLink);
    $('mobileCatList')?.appendChild(mLi);
  });
}

// ═══════════════════════════════════════════════════════════════════
// MENU
// ═══════════════════════════════════════════════════════════════════
function getSortedFiltered(){
  let items=state.activeFilter==='all'?[...state.menu]:state.menu.filter(m=>m.category===state.activeFilter);
  switch(state.activeSort){
    case 'price-asc':  items.sort((a,b)=>a.price-b.price); break;
    case 'price-desc': items.sort((a,b)=>b.price-a.price); break;
    case 'hits':       items.sort((a,b)=>(b.badge==='хит'?1:0)-(a.badge==='хит'?1:0)); break;
    case 'new':        items.sort((a,b)=>(b.badge==='новинка'?1:0)-(a.badge==='новинка'?1:0)); break;
    case 'fav':        items=items.filter(m=>state.favorites.has(m.id)); break;
  }
  return items;
}

function renderMenu(){
  const grid=$('menuGrid'); grid.innerHTML='';
  const items=getSortedFiltered();
  if(!items.length){
    if(state.activeSort==='fav'){
      const msg=ce('div',{class:'menu-empty'}); msg.innerHTML='♡<br>Нет избранных блюд. Нажмите ♡ на карточке, чтобы добавить.';
      grid.appendChild(msg);
    } else {
      const msg=ce('div',{class:'menu-empty'}); msg.textContent='Блюда не найдены'; grid.appendChild(msg);
    }
    return;
  }
  items.forEach(item=>{
    const card=document.createElement('div'); card.className='menu-card'; card.setAttribute('role','listitem');
    const imgWrap=document.createElement('div'); imgWrap.className='menu-card-img';
    imgWrap.appendChild(renderImg(item));
    if(item.badge){
      const badge=ce('div',{class:'menu-badge'+(item.badge==='новинка'?' new':item.badge==='акция'?' akc':'')});
      badge.textContent=item.badge; imgWrap.appendChild(badge);
    }
    // Favorite button
    const favBtn=document.createElement('button');
    favBtn.className='fav-btn'+(state.favorites.has(item.id)?' active':'');
    favBtn.textContent=state.favorites.has(item.id)?'♥':'♡';
    favBtn.setAttribute('aria-label',(state.favorites.has(item.id)?'Убрать из':'Добавить в')+' избранное: '+item.name);
    favBtn.addEventListener('click',e=>{ e.stopPropagation(); toggleFavorite(item.id,favBtn); });
    imgWrap.appendChild(favBtn);
    const body=document.createElement('div'); body.className='menu-card-body';
    const catLbl=ce('div',{class:'menu-cat-label'}); catLbl.textContent=item.category;
    const nameLbl=ce('div',{class:'menu-card-name'}); nameLbl.textContent=item.name;
    const descLbl=ce('div',{class:'menu-card-desc'}); descLbl.textContent=item.description||'';
    // Char counter is handled server-side; no maxlength needed here
    const footer=document.createElement('div'); footer.className='menu-card-footer';
    const price=ce('div',{class:'menu-card-price'}); price.textContent=item.price.toLocaleString('ru-RU')+' ₽';
    const addBtn=ce('button',{class:'btn-add','aria-label':'Добавить '+item.name+' в корзину'});
    addBtn.textContent='+ В корзину'; addBtn.addEventListener('click',()=>addToCart(item.id));
    footer.append(price,addBtn); body.append(catLbl,nameLbl,descLbl,footer);
    card.append(imgWrap,body); grid.appendChild(card);
  });
}

// FAVORITES
function toggleFavorite(id,btn){
  if(state.favorites.has(id)){
    state.favorites.delete(id);
    if(btn){ btn.textContent='♡'; btn.classList.remove('active'); }
    showToast('Убрано из избранного');
  } else {
    state.favorites.add(id);
    if(btn){ btn.textContent='♥'; btn.classList.add('active'); }
    showToast('♥ Добавлено в избранное');
  }
  localStorage.setItem('sc_favs',JSON.stringify([...state.favorites]));
  if(state.activeSort==='fav') renderMenu();
}

function filterMenu(cat,clickedCard){
  state.activeFilter=cat;
  document.querySelectorAll('.cat-card').forEach(c=>c.classList.remove('active'));
  if(clickedCard) clickedCard.classList.add('active');
  document.querySelectorAll('.filter-btn').forEach(b=>b.classList.toggle('active',b.dataset.cat===cat));
  renderMenu();
  $('menu-section').scrollIntoView({behavior:'smooth'});
}

$('sortSelect').addEventListener('change',e=>{ state.activeSort=e.target.value; renderMenu(); });

// ═══════════════════════════════════════════════════════════════════
// SEARCH
// ═══════════════════════════════════════════════════════════════════
$('searchToggle').addEventListener('click',()=>{
  const box=$('searchBox');
  const open=box.classList.toggle('open');
  $('searchToggle').setAttribute('aria-expanded',open);
  $('searchBox').setAttribute('aria-hidden',!open);
  if(open) setTimeout(()=>$('searchInput').focus(),80);
});

$('searchInput').addEventListener('input',()=>{
  const q=$('searchInput').value.trim().toLowerCase();
  const res=$('searchResults'); res.innerHTML='';
  if(!q) return;
  const found=state.menu.filter(m=>
    m.name.toLowerCase().includes(q)||(m.description||'').toLowerCase().includes(q)||m.category.toLowerCase().includes(q)
  ).slice(0,6);
  if(!found.length){ const msg=ce('div',{class:'search-no-results'}); msg.textContent='Ничего не найдено'; res.appendChild(msg); return; }
  found.forEach(item=>{
    const row=document.createElement('div'); row.className='search-result-item';
    row.setAttribute('role','option'); row.setAttribute('tabindex','0');
    const photo=getPhoto(item);
    if(photo){ const img=ce('img',{src:photo,class:'search-result-img',alt:'',loading:'lazy'}); img.addEventListener('error',()=>img.remove()); row.appendChild(img); }
    else { const em=ce('span',{style:'font-size:1.6rem;width:40px;text-align:center'}); em.textContent=item.emoji||'🍽'; row.appendChild(em); }
    const info=document.createElement('div');
    const nm=ce('div',{class:'search-result-name'}); nm.textContent=item.name;
    const pr=ce('div',{class:'search-result-price'}); pr.textContent=item.price.toLocaleString('ru-RU')+' ₽';
    info.append(nm,pr); row.appendChild(info);
    row.addEventListener('click',()=>{ addToCart(item.id); $('searchBox').classList.remove('open'); $('searchInput').value=''; $('searchResults').innerHTML=''; });
    row.addEventListener('keydown',e=>{ if(e.key==='Enter') row.click(); });
    res.appendChild(row);
  });
});

document.addEventListener('click',e=>{ if(!e.target.closest('.search-wrap')) $('searchBox').classList.remove('open'); });

// ═══════════════════════════════════════════════════════════════════
// CART
// ═══════════════════════════════════════════════════════════════════
function addToCart(id){
  const item=state.menu.find(m=>m.id===id); if(!item) return;
  const ex=state.cart.find(c=>c.id===id);
  if(ex) ex.qty++; else state.cart.push({id:item.id,qty:1});
  updateCartUI(); showToast((item.emoji||'')+(item.emoji?' ':'')+item.name+' добавлен!');
  revalidatePromo();
}

function removeFromCart(id){
  const ex=state.cart.find(c=>c.id===id); if(!ex) return;
  if(ex.qty>1) ex.qty--; else state.cart=state.cart.filter(c=>c.id!==id);
  updateCartUI(); revalidatePromo();
}

// FIX: re-validate promo when cart changes
function revalidatePromo(){
  if(!state.appliedPromo) return;
  const {subtotal}=calcCart();
  if(subtotal<(state.appliedPromo.min_sum||0)){
    state.appliedPromo=null;
    $('promoResult').textContent='⚠ Промокод отменён: сумма ниже минимума';
    $('promoResult').className='promo-result err';
    updateCartUI();
  }
}

function calcCart(){
  const subtotal=state.cart.reduce((s,c)=>{
    const item=state.menu.find(m=>m.id===c.id);
    return s+(item?item.price*c.qty:0);
  },0);
  let discount=0;
  if(state.appliedPromo){
    const p=state.appliedPromo;
    if(subtotal>=(p.min_sum||0)){
      discount=p.type==='percent'?Math.round(subtotal*p.value/100):Math.min(p.value,subtotal);
    }
  }
  return {subtotal,discount,total:subtotal-discount};
}

function updateCartUI(){
  const count=state.cart.reduce((s,c)=>s+c.qty,0);
  $('cartCount').textContent=count;
  $('cartBtn').setAttribute('aria-label','Корзина, товаров: '+count);
  const {subtotal,discount,total}=calcCart();
  $('cartSubtotal').textContent=subtotal.toLocaleString('ru-RU')+' ₽';
  $('cartTotal').textContent=total.toLocaleString('ru-RU')+' ₽';
  $('cartDiscount').textContent='−'+discount.toLocaleString('ru-RU')+' ₽';
  $('discountRow').style.display=discount>0?'':'none';
  const container=$('cartItems'); container.innerHTML='';
  if(!state.cart.length){
    const msg=document.createElement('div'); msg.className='cart-empty'; msg.innerHTML='🛒<br>Корзина пуста'; container.appendChild(msg);
    updatePromoProgress(); return;
  }
  state.cart.forEach(c=>{
    const item=state.menu.find(m=>m.id===c.id); if(!item) return;
    const row=document.createElement('div'); row.className='cart-item';
    const photo=getPhoto(item);
    if(photo){
      const img=ce('img',{src:photo,class:'cart-item-thumb',alt:'',loading:'lazy'});
      img.addEventListener('error',()=>{ const em=ce('span',{class:'cart-item-emoji'}); em.textContent=item.emoji||'🍽'; img.replaceWith(em); });
      row.appendChild(img);
    } else { const em=ce('span',{class:'cart-item-emoji'}); em.textContent=item.emoji||'🍽'; row.appendChild(em); }
    const info=document.createElement('div'); info.className='cart-item-info';
    const nm=ce('div',{class:'cart-item-name'}); nm.textContent=item.name;
    const pr=ce('div',{class:'cart-item-price'});
    pr.textContent=item.price.toLocaleString('ru-RU')+' ₽ × '+c.qty+' = '+(item.price*c.qty).toLocaleString('ru-RU')+' ₽';
    info.append(nm,pr);
    const qty=document.createElement('div'); qty.className='cart-item-qty';
    const btnM=ce('button',{class:'qty-btn','aria-label':'Убрать '+item.name}); btnM.textContent='−'; btnM.addEventListener('click',()=>removeFromCart(item.id));
    const num=ce('span',{class:'qty-num'}); num.textContent=c.qty;
    const btnP=ce('button',{class:'qty-btn','aria-label':'Добавить '+item.name}); btnP.textContent='+'; btnP.addEventListener('click',()=>addToCart(item.id));
    qty.append(btnM,num,btnP); row.append(info,qty); container.appendChild(row);
  });
  updatePromoProgress();
}

// ═══════════════════════════════════════════════════════════════════
// PROMO PROGRESS BAR
// ═══════════════════════════════════════════════════════════════════
function updatePromoProgress(){
  const bar=$('promoProgressWrap'); if(!bar) return;
  if(state.appliedPromo){ bar.style.display='none'; return; }
  const promos=state.promos.filter(p=>p.min_sum>0&&p.active!==0);
  if(!promos.length){ bar.style.display='none'; return; }
  const nearest=promos.reduce((a,b)=>a.min_sum<b.min_sum?a:b);
  const {subtotal}=calcCart();
  if(subtotal>=nearest.min_sum){ bar.style.display='none'; return; }
  const left=nearest.min_sum-subtotal;
  bar.style.display='';
  $('promoProgressText').textContent=`Добавьте ещё ${left.toLocaleString('ru-RU')} ₽ для промокода «${nearest.code}»`;
  const pct=Math.min(100,Math.round(subtotal/nearest.min_sum*100));
  $('promoProgressBar').style.width=pct+'%';
}

$('applyPromoBtn').addEventListener('click',applyPromo);
$('promoInput').addEventListener('keydown',e=>{ if(e.key==='Enter') applyPromo(); });

async function applyPromo(){
  const code=$('promoInput').value.trim().toUpperCase();
  const res=$('promoResult');
  if(!code){ res.textContent='⚠ Введите промокод'; res.className='promo-result err'; return; }
  const {subtotal}=calcCart();
  try {
    const data=await POST('/promos/validate',{code,amount:subtotal});
    state.appliedPromo={code,type:data.type,value:data.value,min_sum:data.min_sum||0};
    const disc=data.type==='percent'?data.value+'%':data.value.toLocaleString('ru-RU')+' ₽';
    res.textContent=`✅ ${data.description} (−${disc})`; res.className='promo-result ok';
    updateCartUI();
  } catch(e){
    state.appliedPromo=null; res.textContent='❌ '+e.message; res.className='promo-result err'; updateCartUI();
  }
}

// ═══════════════════════════════════════════════════════════════════
// CHECKOUT — multi-step with server submission
// ═══════════════════════════════════════════════════════════════════
function openCheckout(){
  if(!state.cart.length){ showToast('⚠ Корзина пуста'); return; }
  // FIX: reset all fields on open
  currentCheckoutStep=1;
  ['co-name','co-phone','co-email','co-addr','co-flat','co-floor','co-intercom','co-comment'].forEach(id=>{ const el=$(id); if(el) el.value=''; });
  $('co-agree').checked=false; $('agreeError').textContent='';
  document.querySelectorAll('input[name="delivery"]')[0].checked=true;
  $('deliveryFields').style.display='';
  renderCheckoutStep(); closeCart(); openModal('checkoutModal');
}

function renderCheckoutStep(){
  for(let i=1;i<=3;i++) $('cstep-'+i).style.display=i===currentCheckoutStep?'':'none';
  document.querySelectorAll('.checkout-steps .step').forEach((s,idx)=>{
    s.classList.remove('active','done');
    if(idx+1<currentCheckoutStep) s.classList.add('done');
    if(idx+1===currentCheckoutStep) s.classList.add('active');
  });
  $('coPrevBtn').style.display=currentCheckoutStep>1?'':'none';
  $('coNextBtn').style.display=currentCheckoutStep<3?'':'none';
  $('coSubmitBtn').style.display=currentCheckoutStep===3?'':'none';
  if(currentCheckoutStep===3){
    const summary=$('coSummaryItems'); summary.innerHTML='';
    state.cart.forEach(c=>{
      const item=state.menu.find(m=>m.id===c.id); if(!item) return;
      const row=ce('div',{class:'co-sum-item'});
      const nm=document.createElement('span'); nm.textContent=item.name+' × '+c.qty;
      const pr=document.createElement('span'); pr.textContent=(item.price*c.qty).toLocaleString('ru-RU')+' ₽';
      row.append(nm,pr); summary.appendChild(row);
    });
    const {total}=calcCart(); setText('coTotalFinal',total.toLocaleString('ru-RU')+' ₽');
  }
  document.querySelectorAll('input[name="delivery"]').forEach(r=>{
    r.onchange=()=>{ $('deliveryFields').style.display=r.value==='pickup'?'none':''; };
  });
}

function checkoutNext(){ if(!validateCheckoutStep()) return; currentCheckoutStep++; renderCheckoutStep(); }
function checkoutPrev(){ currentCheckoutStep--; renderCheckoutStep(); }

function validateCheckoutStep(){
  let ok=true;
  if(currentCheckoutStep===1){
    const name=$('co-name').value.trim(); const phone=$('co-phone').value.trim();
    if(!name){ markError($('co-name'),'Введите имя'); ok=false; } else clearError($('co-name'));
    if(!phone||phone.replace(/\D/g,'').length<10){ markError($('co-phone'),'Введите телефон (10+ цифр)'); ok=false; } else clearError($('co-phone'));
  } else if(currentCheckoutStep===2){
    const delivery=document.querySelector('input[name="delivery"]:checked')?.value;
    if(delivery==='delivery'){ const addr=$('co-addr').value.trim(); if(!addr){ markError($('co-addr'),'Введите адрес'); ok=false; } else clearError($('co-addr')); }
  }
  return ok;
}

function markError(input,msg){ input.classList.add('error'); const e=input.closest('.form-group')?.querySelector('.field-error'); if(e) e.textContent=msg; }
function clearError(input){ input.classList.remove('error'); const e=input.closest('.form-group')?.querySelector('.field-error'); if(e) e.textContent=''; }

$('checkoutForm').addEventListener('submit',async e=>{
  e.preventDefault();
  if(!$('co-agree').checked){ $('agreeError').textContent='Необходимо согласиться с условиями'; return; }
  $('agreeError').textContent='';
  await placeOrder();
});

async function placeOrder(){
  const delivery=document.querySelector('input[name="delivery"]:checked')?.value||'delivery';
  const payment=document.querySelector('input[name="payment"]:checked')?.value||'cash';
  const payload={
    name:$('co-name').value.trim(), phone:$('co-phone').value.trim(), email:$('co-email').value.trim(),
    delivery_type:delivery, address:$('co-addr')?.value.trim()||'', flat:$('co-flat')?.value.trim()||'',
    floor:$('co-floor')?.value.trim()||'', intercom:$('co-intercom')?.value.trim()||'',
    delivery_time:$('co-time')?.value||'asap', comment:$('co-comment')?.value.trim()||'',
    payment, promo_code:state.appliedPromo?.code||'', items:state.cart.map(c=>({id:c.id,qty:c.qty})),
  };
  $('coSubmitBtn').disabled=true; $('coSubmitBtn').textContent='Отправляем…';
  try {
    const data=await POST('/orders',payload);
    closeModal('checkoutModal');
    state.cart=[]; state.appliedPromo=null; $('promoInput').value=''; $('promoResult').textContent='';
    updateCartUI(); showTracking(data.order_num);
  } catch(e){ showToast('❌ '+e.message); }
  finally { $('coSubmitBtn').disabled=false; $('coSubmitBtn').textContent='✓ Подтвердить заказ'; }
}

function showTracking(orderNum){
  setText('trackingOrderId','#'+orderNum);
  // FIX: correct operator precedence with parentheses
  const heroTimeEl=$('heroTime');
  setText('trackingETA','~'+(heroTimeEl?heroTimeEl.textContent:'30 мин'));
  ['ts-prep','ts-way','ts-done'].forEach(id=>$( id).classList.remove('active','done'));
  openModal('trackingModal');
  setTimeout(()=>{ $('ts-prep').classList.add('active'); },2000);
  setTimeout(()=>{ $('ts-prep').classList.replace('active','done'); $('ts-way').classList.add('active'); },6000);
  setTimeout(()=>{ $('ts-way').classList.replace('active','done'); $('ts-done').classList.add('active'); },12000);
  setTimeout(()=>{ $('ts-done').classList.replace('active','done'); },16000);
}

// ═══════════════════════════════════════════════════════════════════
// REVIEWS
// ═══════════════════════════════════════════════════════════════════
function renderReviews(){
  const grid=$('reviewsGrid'); grid.innerHTML='';
  const approved=state.reviews.filter(r=>r.approved||r.approved===1);
  if(!approved.length){ const msg=ce('div',{class:'review-empty'}); msg.textContent='Отзывов пока нет. Будьте первым!'; grid.appendChild(msg); return; }
  [...approved].sort((a,b)=>new Date(b.created_at)-new Date(a.created_at)).forEach(r=>{
    const card=document.createElement('div'); card.className='review-card'; card.setAttribute('role','listitem');
    const header=document.createElement('div'); header.className='review-header';
    const av=ce('div',{class:'review-avatar'}); av.textContent=r.name.charAt(0).toUpperCase();
    const meta=document.createElement('div');
    const nm=ce('div',{class:'review-name'}); nm.textContent=r.name;
    const dt=ce('div',{class:'review-date'}); dt.textContent=r.created_at?new Date(r.created_at).toLocaleDateString('ru-RU'):'';
    meta.append(nm,dt); header.append(av,meta);
    const stars=ce('div',{class:'review-stars'}); stars.textContent='★'.repeat(r.rating)+'☆'.repeat(5-r.rating);
    const text=ce('p',{class:'review-text'}); text.textContent=r.text;
    card.append(header,stars,text); grid.appendChild(card);
  });
}

$('addReviewBtn').addEventListener('click',()=>{
  currentRating=0; $('rev-name').value=''; $('rev-text').value='';
  $('rev-rating').value='0'; document.querySelectorAll('.star').forEach(s=>s.classList.remove('active'));
  openModal('reviewModal');
});

document.querySelectorAll('.star').forEach(star=>{
  star.addEventListener('click',()=>{
    currentRating=parseInt(star.dataset.v); $('rev-rating').value=currentRating;
    document.querySelectorAll('.star').forEach(s=>s.classList.toggle('active',parseInt(s.dataset.v)<=currentRating));
  });
  star.addEventListener('mouseover',()=>{
    const v=parseInt(star.dataset.v);
    document.querySelectorAll('.star').forEach(s=>s.classList.toggle('active',parseInt(s.dataset.v)<=v));
  });
  star.addEventListener('mouseout',()=>{
    document.querySelectorAll('.star').forEach(s=>s.classList.toggle('active',parseInt(s.dataset.v)<=currentRating));
  });
});

$('reviewForm').addEventListener('submit',async e=>{
  e.preventDefault(); let ok=true;
  const name=$('rev-name').value.trim(); const text=$('rev-text').value.trim(); const rating=currentRating;
  if(!name){ markError($('rev-name'),'Введите имя'); ok=false; } else clearError($('rev-name'));
  if(!rating){ $('ratingError').textContent='Поставьте оценку'; ok=false; } else $('ratingError').textContent='';
  if(!text){ markError($('rev-text'),'Напишите отзыв'); ok=false; } else clearError($('rev-text'));
  if(text.length>1000){ markError($('rev-text'),'Максимум 1000 символов'); ok=false; }
  if(!ok) return;
  try { await POST('/reviews',{name,rating,text}); closeModal('reviewModal'); showToast('✅ Спасибо! Отзыв отправлен на модерацию.'); }
  catch(err){ showToast('❌ '+err.message); }
});

// char counter for review textarea
$('rev-text')?.addEventListener('input',function(){
  let counter=$('rev-text-counter');
  if(!counter){ counter=ce('span',{id:'rev-text-counter',style:'font-size:0.72rem;color:#aaa;text-align:right;display:block;margin-top:2px'}); this.parentNode.insertBefore(counter,this.nextSibling); }
  counter.textContent=this.value.length+'/1000';
  if(this.value.length>1000) counter.style.color='#e74c3c'; else counter.style.color='#aaa';
});

// ═══════════════════════════════════════════════════════════════════
// AUTH — universal login/register system
// ═══════════════════════════════════════════════════════════════════
async function checkAuthStatus(){
  try {
    const data=await GET('/auth/me');
    state.currentUser=data;
    updateAuthUI();
  } catch(_){ state.currentUser=null; updateAuthUI(); }
}

function updateAuthUI(){
  // Remove old buttons
  $('adminBtn')?.remove(); $('userBtn')?.remove(); $('authNavBtn')?.remove();
  const navRight=$('navRight');
  if(!navRight) return;

  if(state.currentUser){
    const role=state.currentUser.role;
    // User menu button
    const btn=document.createElement('button'); btn.id='userBtn'; btn.className='btn-user-nav';
    const initial=(state.currentUser.full_name||state.currentUser.username||'U').charAt(0).toUpperCase();
    btn.innerHTML='<span class="user-avatar-sm">'+initial+'</span><span class="user-nav-name">'+esc(state.currentUser.full_name||state.currentUser.username)+'</span>';
    btn.addEventListener('click',()=>{
      if(role==='admin') openAdmin();
      else if(role==='manager') openAdmin();
      else openClientPanel();
    });
    navRight.prepend(btn);
    // Admin/manager get extra button
    if(role==='admin'||role==='manager'){
      const abtn=document.createElement('button'); abtn.id='adminBtn'; abtn.className='btn-admin-nav';
      abtn.textContent=role==='admin'?'⚙ Админ':'📋 Заказы';
      abtn.addEventListener('click',openAdmin);
      navRight.prepend(abtn);
    }
  } else {
    const btn=document.createElement('button'); btn.id='authNavBtn'; btn.className='btn-auth-nav';
    btn.textContent='👤 Войти'; btn.addEventListener('click',()=>openAuthModal('login'));
    navRight.prepend(btn);
  }
}

// ── Auth Modal ────────────────────────────────────────────────────
function openAuthModal(tab='login'){
  switchAuthTab(tab);
  $('loginUsername').value=''; $('loginPassword').value='';
  $('loginError').textContent=''; $('loginError').classList.remove('show');
  $('loginAttempts').textContent='';
  clearRegForm();
  openModal('authModal');
  setTimeout(()=>$(tab==='register'?'regName':'loginUsername').focus(),100);
}

function switchAuthTab(tab){
  document.querySelectorAll('.auth-tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===tab));
  $('authLogin').style.display=tab==='login'?'':'none';
  $('authRegister').style.display=tab==='register'?'':'none';
  $('authForgotMsg').style.display=tab==='forgot'?'':'none';
  $('authTabs').style.display=tab==='forgot'?'none':'';
  $('authTitle').textContent=tab==='login'?'Вход в систему':tab==='register'?'Регистрация':'Восстановление пароля';
}

function showForgotMsg(){
  switchAuthTab('forgot');
  const s=state.settings;
  if(s.phone) $('forgotPhone').textContent=s.phone;
  if(s.email) $('forgotEmail').textContent=s.email;
}

function clearRegForm(){
  ['regName','regUsername','regEmail','regPhone','regPassword','regConfirm'].forEach(id=>{const e=$(id);if(e)e.value='';});
  ['regNameErr','regUsernameErr','regEmailErr','regPassErr','regConfirmErr','regError'].forEach(id=>{const e=$(id);if(e){e.textContent='';e.classList.remove('show');}});
}

// Auth tabs click handler
document.querySelectorAll('.auth-tab').forEach(tab=>{
  tab.addEventListener('click',()=>switchAuthTab(tab.dataset.tab));
});

// ── Login ─────────────────────────────────────────────────────────
async function submitLogin(){
  const username=$('loginUsername').value.trim(); const password=$('loginPassword').value;
  if(!username||!password){ showLoginError('Введите логин и пароль.'); return; }
  $('loginSubmitBtn').disabled=true; $('loginSubmitBtn').textContent='Вход…';
  try {
    const data=await POST('/auth/login',{username,password});
    state.currentUser=data;
    closeModal('authModal'); updateAuthUI();
    showToast('✅ Добро пожаловать, '+esc(data.full_name||data.username));
    if(data.role==='admin'||data.role==='manager') openAdmin();
    else if(data.role==='client') openClientPanel();
  } catch(err){
    showLoginError(err.message||'Ошибка входа'); shakeAuthCard(); $('loginPassword').value='';
    if(err.message?.includes('попыток')||err.message?.includes('Заблок')) $('loginAttempts').textContent=err.message;
  } finally { $('loginSubmitBtn').disabled=false; $('loginSubmitBtn').textContent='Войти →'; }
}

$('loginSubmitBtn').addEventListener('click',submitLogin);

function showLoginError(msg){ const e=$('loginError'); e.textContent=msg; e.classList.add('show'); }
function shakeAuthCard(){ const c=document.querySelector('.auth-card'); if(!c) return; c.style.animation='none'; void c.offsetWidth; c.style.animation='shake .4s ease'; }
$('togglePass').addEventListener('click',()=>toggleFieldPass('loginPassword'));
function toggleFieldPass(id){ const inp=$(id); if(!inp) return; inp.type=inp.type==='password'?'text':'password'; }
$('loginPassword').addEventListener('keydown',e=>{ if(e.key==='Enter') submitLogin(); });
$('loginUsername').addEventListener('keydown',e=>{ if(e.key==='Enter') $('loginPassword').focus(); });

// ── Register ──────────────────────────────────────────────────────
$('regSubmitBtn').addEventListener('click',submitRegister);
async function submitRegister(){
  let ok=true;
  const name=$('regName').value.trim();
  const username=$('regUsername').value.trim();
  const email=$('regEmail').value.trim();
  const phone=$('regPhone').value.trim();
  const password=$('regPassword').value;
  const confirm=$('regConfirm').value;

  $('regNameErr').textContent=''; $('regUsernameErr').textContent=''; $('regEmailErr').textContent='';
  $('regPassErr').textContent=''; $('regConfirmErr').textContent=''; $('regError').textContent=''; $('regError').classList.remove('show');

  if(!name){ $('regNameErr').textContent='Введите имя'; ok=false; }
  if(!username||username.length<3){ $('regUsernameErr').textContent='Минимум 3 символа'; ok=false; }
  if(password.length<8){ $('regPassErr').textContent='Минимум 8 символов'; ok=false; }
  if(password!==confirm){ $('regConfirmErr').textContent='Пароли не совпадают'; ok=false; }
  if(!ok) return;

  $('regSubmitBtn').disabled=true; $('regSubmitBtn').textContent='Создание…';
  try {
    const data=await POST('/auth/register',{full_name:name,username,email,phone,password,confirm});
    state.currentUser=data;
    closeModal('authModal'); updateAuthUI();
    showToast('🎉 Добро пожаловать, '+esc(data.full_name||data.username)+'!');
  } catch(err){
    const e=$('regError'); e.textContent=err.message||'Ошибка регистрации'; e.classList.add('show');
    shakeAuthCard();
  } finally { $('regSubmitBtn').disabled=false; $('regSubmitBtn').textContent='Создать аккаунт'; }
}

// ── Logout ─────────────────────────────────────────────────────────
async function doLogout(){
  try { await POST('/auth/logout',{}); } catch(_){}
  state.currentUser=null; closeAdmin(); closeClientPanel(); updateAuthUI();
  showToast('🔒 Вы вышли из системы');
}
async function adminLogout(){ await doLogout(); }

// ═══════════════════════════════════════════════════════════════════
// CLIENT PANEL
// ═══════════════════════════════════════════════════════════════════
function openClientPanel(){
  if(!state.currentUser) { openAuthModal('login'); return; }
  $('clientNameBadge').textContent=state.currentUser.full_name||state.currentUser.username;
  $('clientPanel').classList.add('open'); $('overlay').classList.add('show');
  loadClientOrders();
  // Fill profile
  const u=state.currentUser;
  $('cp-name').value=u.full_name||''; $('cp-email').value=u.email||''; $('cp-phone').value=u.phone||'';
}
function closeClientPanel(){ $('clientPanel').classList.remove('open'); $('overlay').classList.remove('show'); }
$('closeClient')?.addEventListener('click',closeClientPanel);

// Client tabs
document.querySelectorAll('.ctab').forEach(tab=>{
  tab.addEventListener('click',()=>{
    document.querySelectorAll('.ctab').forEach(t=>{t.classList.remove('active');t.setAttribute('aria-selected','false');});
    document.querySelectorAll('.ctab-content').forEach(c=>c.classList.remove('active'));
    tab.classList.add('active'); tab.setAttribute('aria-selected','true');
    $('ctab-'+tab.dataset.tab)?.classList.add('active');
  });
});

async function loadClientOrders(){
  const list=$('clientOrdersList'); if(!list) return;
  list.innerHTML='<p style="color:#999;font-size:0.85rem">Загрузка…</p>';
  try {
    const orders=await GET('/client/orders');
    list.innerHTML='';
    if(!orders.length){ list.innerHTML='<p style="color:#999;text-align:center;padding:32px 0">📦 Заказов пока нет</p>'; return; }
    orders.forEach(o=>{
      const card=document.createElement('div'); card.className='client-order-card';
      const statusMap={new:'🆕 Новый',confirmed:'✅ Подтверждён',preparing:'👨‍🍳 Готовится',delivering:'🚴 В пути',done:'✔ Доставлен',cancelled:'❌ Отменён'};
      card.innerHTML=`<div class="co-header"><span class="co-num">#${esc(o.order_num)}</span><span class="co-status">${statusMap[o.status]||o.status}</span></div>`
        +`<div class="co-items">${(o.items||[]).map(i=>esc(i.name)+' ×'+i.qty).join(', ')}</div>`
        +`<div class="co-footer"><span class="co-total">${o.total.toLocaleString('ru-RU')} ₽</span><span class="co-date">${(o.created_at||'').slice(0,16)}</span></div>`;
      list.appendChild(card);
    });
  } catch(e){ list.innerHTML='<p style="color:#e74c3c">Ошибка загрузки</p>'; }
}

async function saveClientProfile(){
  const err=$('cpError'); err.textContent=''; err.classList.remove('show');
  const full_name=$('cp-name').value.trim();
  const email=$('cp-email').value.trim();
  const phone=$('cp-phone').value.trim();
  if(!full_name){ err.textContent='Введите имя'; err.classList.add('show'); return; }
  try {
    await api('PUT','/auth/profile',{full_name,email,phone});
    state.currentUser.full_name=full_name; state.currentUser.email=email; state.currentUser.phone=phone;
    updateAuthUI(); showToast('✅ Профиль обновлён');
  } catch(e){ err.textContent=e.message; err.classList.add('show'); }
}

async function changeClientPassword(){
  const err=$('cpPassError'); err.textContent=''; err.classList.remove('show');
  const old_pass=$('cp-oldPass').value;
  const new_pass=$('cp-newPass').value;
  const confirm=$('cp-confirmPass').value;
  if(!old_pass){ err.textContent='Введите текущий пароль'; err.classList.add('show'); return; }
  if(new_pass.length<8){ err.textContent='Минимум 8 символов'; err.classList.add('show'); return; }
  if(new_pass!==confirm){ err.textContent='Пароли не совпадают'; err.classList.add('show'); return; }
  try {
    await POST('/auth/change-password',{old_pass,new_pass,confirm});
    $('cp-oldPass').value=''; $('cp-newPass').value=''; $('cp-confirmPass').value='';
    showToast('🔒 Пароль изменён');
  } catch(e){ err.textContent=e.message; err.classList.add('show'); }
}

// ═══════════════════════════════════════════════════════════════════
// ═══════════════════════════════════════════════════════════════════
// ADMIN PANEL — FULLSCREEN COMMAND CENTER
// ═══════════════════════════════════════════════════════════════════
const adminUI = {
  activeTab: 'admOrders',
  clockTimer: null,

  async open() {
    if(!state.currentUser||!['admin','manager'].includes(state.currentUser.role)){ openAuthModal('login'); return; }
    
    // Load fresh data
    try { 
      const [promos, settings] = await Promise.all([GET('/promos'), GET('/settings')]);
      state.promos = promos;
      state.settings = settings;
    } catch(e){ console.error('Admin data load fail', e); }

    $('adminPanel').classList.add('open');
    document.body.style.overflow = 'hidden'; // Lock scroll
    
    this.startClock();
    this.renderActiveTab();
    this.fillSettingsForm();
  },

  close() {
    $('adminPanel').classList.remove('open');
    document.body.style.overflow = '';
    if(this.clockTimer) clearInterval(this.clockTimer);
  },

  startClock() {
    const el = $('adminClock');
    const update = () => { if(el) el.textContent = new Date().toLocaleString('ru-RU', {hour:'2-digit', minute:'2-digit', second:'2-digit'}); };
    update();
    this.clockTimer = setInterval(update, 1000);
  },

  switchTab(tabId) {
    this.activeTab = tabId;
    document.querySelectorAll('.atab').forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
    document.querySelectorAll('.atab-content').forEach(c => c.classList.toggle('active', c.id === tabId));
    
    const titles = {
      admOrders: '🥡 Управление заказами',
      admMenu: '🍕 Меню и Блюда',
      admCats: '📁 Категории',
      admPromo: '🎟️ Промокоды',
      admReviews: '💬 Отзывы',
      admUsers: '👥 Пользователи',
      admSettings: '⚙️ Настройки сайта'
    };
    setText('adminCurrentTabTitle', titles[tabId] || 'Админ');
    this.renderActiveTab();
  },

  renderActiveTab() {
    switch(this.activeTab) {
      case 'admOrders': loadAdminOrders(); break;
      case 'admMenu': renderAdminMenu(); break;
      case 'admCats': renderAdminCats(); break;
      case 'admPromo': renderAdminPromos(); break;
      case 'admReviews': renderAdminReviews(); break;
      case 'admUsers': loadAdminUsers(); break;
      case 'admSettings': this.fillSettingsForm(); break;
    }
  },

  fillSettingsForm() {
    const f = $('settingsForm');
    if(!f) return;
    const s = state.settings;
    for(let field of f.elements) {
      if(field.name && s[field.name] !== undefined) {
        if(field.type === 'checkbox') field.checked = !!s[field.name];
        else field.value = s[field.name];
      }
    }
    const colorPick = $('primaryColorPick');
    if(colorPick) colorPick.value = s.accent_color || '#F5C518';
  },

  resetMenuForm() {
    editingMenuId = null;
    $('menuForm').reset();
    $('menuId').value = '';
    const h4 = $('menuForm').closest('.adm-card').querySelector('h4');
    if(h4) h4.textContent = 'Добавить / Редактировать блюдо';
  }
};

// Event Delegation for Admin Tabs
$('adminTabs')?.addEventListener('click', e => {
  const btn = e.target.closest('.atab');
  if(btn) adminUI.switchTab(btn.dataset.tab);
});


// Update legacy aliases
async function openAdmin(){ adminUI.open(); }
function closeAdmin(){ adminUI.close(); }

// ── Admin Menu ──────────────────────────────────────────────────────
function renderAdminMenu(){
  const list=$('adminMenuContainer'); if(!list) return;
  list.innerHTML='';
  // Update category select in form
  const sel = $('menuCat');
  if(sel) {
    sel.innerHTML = '<option value="">Выберите категорию...</option>';
    state.categories.forEach(c => {
      const opt = ce('option', {value: c.name}, c.name);
      sel.appendChild(opt);
    });
  }

  state.menu.forEach(item=>{
    const row=document.createElement('div'); row.className='adm-list-item';
    const info=document.createElement('div'); info.style.cssText='display:flex;align-items:center;gap:15px;flex:1;min-width:0';
    
    const box = ce('div', {class:'user-avatar-lg', style:'background: #f1f5f9;'});
    box.textContent = item.emoji || '🍕';
    info.appendChild(box);

    const meta=document.createElement('div'); meta.style.cssText='min-width:0';
    const nm=ce('div',{class:'adm-list-item-name', style:'font-weight: 800;'}); nm.textContent=item.name;
    const mt=ce('div',{class:'adm-list-item-meta'}); mt.textContent=item.category+' · '+item.price.toLocaleString('ru-RU')+' ₽';
    meta.append(nm,mt); info.appendChild(meta);
    
    const actions=document.createElement('div'); actions.className='adm-list-item-actions';
    const editBtn=ce('button',{class:'btn-adm btn-adm-cancel', style:'padding: 8px 12px; font-size: 0.8rem;'}); editBtn.textContent='Изменить'; 
    editBtn.addEventListener('click',()=>startEditMenuItem(item.id));
    const delBtn=ce('button',{class:'btn-adm btn-adm-danger', style:'padding: 8px 12px; font-size: 0.8rem;'}); delBtn.textContent='Удалить'; 
    delBtn.addEventListener('click',()=>deleteMenuItem(item.id));
    
    actions.append(editBtn,delBtn); row.append(info,actions); list.appendChild(row);
  });
}

function startEditMenuItem(id){
  const item=state.menu.find(m=>m.id===id); if(!item) return;
  editingMenuId = id;
  $('menuId').value = id;
  $('menuName').value = item.name;
  $('menuPrice').value = item.price;
  $('menuCat').value = item.category;
  $('menuDesc').value = item.description || '';
  $('menuEmoji').value = item.emoji || '';
  $('menuPhoto').value = item.photo_url || '';
  $('menuDiscount').value = item.discount || 0;
  
  const h4 = $('menuForm').closest('.adm-card').querySelector('h4');
  if(h4) h4.textContent = '✏️ Редактирование: ' + item.name;
  $('menuForm').scrollIntoView({behavior:'smooth', block:'center'});
}

$('menuForm')?.addEventListener('submit', async e => {
  e.preventDefault();
  const body = {
    name: $('menuName').value.trim(),
    category: $('menuCat').value,
    price: parseInt($('menuPrice').value),
    description: $('menuDesc').value.trim(),
    emoji: $('menuEmoji').value.trim() || '🍕',
    photo_url: $('menuPhoto').value.trim() || null,
    discount: parseInt($('menuDiscount').value) || 0
  };
  
  try {
    if(editingMenuId) {
      await PUT('/menu/'+editingMenuId, body);
      showToast('✅ Блюдо обновлено');
    } else {
      await POST('/menu', body);
      showToast('✅ Блюдо добавлено');
    }
    const menu = await GET('/menu');
    state.menu = menu;
    renderAdminMenu(); renderMenu();
    adminUI.resetMenuForm();
  } catch(err) { showToast('❌ ' + err.message); }
});

async function deleteMenuItem(id){
  if(!confirm('Удалить это блюдо?')) return;
  try {
    await DEL('/menu/'+id);
    state.menu = state.menu.filter(m => m.id !== id);
    renderAdminMenu(); renderMenu();
    showToast('🗑 Удалено');
  } catch(err) { showToast('❌ ' + err.message); }
}

// ── Admin Categories ────────────────────────────────────────────────
function renderAdminCats(){
  const list=$('adminCatsContainer'); if(!list) return;
  list.innerHTML='';
  state.categories.forEach(c=>{
    const row=document.createElement('div'); row.className='adm-list-item';
    row.innerHTML = `<div style="display:flex; align-items:center; gap:12px;">
       <span style="font-size: 1.5rem;">${c.emoji||'📁'}</span>
       <div style="font-weight: 800;">${c.name}</div>
    </div>`;
    const del=ce('button',{class:'btn-adm btn-adm-danger', style:'padding: 6px 12px;'}); del.textContent='Удалить';
    del.addEventListener('click',()=>deleteCategory(c.id));
    row.appendChild(del);
    list.appendChild(row);
  });
}

$('catForm')?.addEventListener('submit', async e => {
  e.preventDefault();
  const body = { name: $('catNameField').value.trim(), emoji: $('catEmojiField').value.trim() };
  try {
    await POST('/categories', body);
    state.categories = await GET('/categories');
    renderAdminCats(); renderCategories();
    $('catForm').reset();
    showToast('✅ Категория добавлена');
  } catch(err) { showToast('❌ ' + err.message); }
});

async function deleteCategory(id){
  if(!confirm('Удалить категорию?')) return;
  try {
    await DEL('/categories/'+id);
    state.categories = state.categories.filter(c => c.id !== id);
    renderAdminCats(); renderCategories();
    showToast('🗑 Удалено');
  } catch(err) { showToast('❌ ' + err.message); }
}

// ── Admin Promos ─────────────────────────────────────────────────────
function renderAdminPromos(){
  const list=$('adminPromoContainer'); if(!list) return;
  list.innerHTML='';
  state.promos.forEach(p=>{
    const row=document.createElement('div'); row.className='adm-list-item';
    row.innerHTML = `<div>
       <div style="font-weight: 800; color: var(--yellow-dark);">${p.code}</div>
       <div style="font-size: 0.8rem; color: var(--gray);">${p.type==='percent'?'Скидка '+p.value+'%':'Минус '+p.value+' ₽'} · 👤 ${p.used_cnt||0}</div>
    </div>`;
    const del=ce('button',{class:'btn-adm btn-adm-danger', style:'padding: 6px 12px;'}); del.textContent='Удалить';
    del.addEventListener('click', async () => {
       try { await DEL('/promos/'+p.id); state.promos = state.promos.filter(x=>x.id!==p.id); renderAdminPromos(); } catch(e){ showToast(e.message); }
    });
    row.appendChild(del);
    list.appendChild(row);
  });
}

$('promoForm')?.addEventListener('submit', async e => {
  e.preventDefault();
  const body = {
    code: $('promoCodeField').value.trim().toUpperCase(),
    value: parseFloat($('promoValField').value),
    type: $('promoTypeField').value,
    min_sum: 0, description: ''
  };
  try {
    await POST('/promos', body);
    state.promos = await GET('/promos');
    renderAdminPromos();
    $('promoForm').reset();
    showToast('✅ Промокод добавлен');
  } catch(err) { showToast('❌ ' + err.message); }
});

// ── Admin Reviews ────────────────────────────────────────────────────
async function renderAdminReviews(){
  const list=$('adminReviewsContainer'); if(!list) return;
  list.innerHTML='';
  try {
    const revs = await GET('/reviews');
    revs.forEach(r => {
      const row=document.createElement('div'); row.className='adm-list-item';
      row.style.flexDirection = 'column'; row.style.alignItems = 'flex-start'; row.style.gap = '8px';
      row.innerHTML = `<div style="display:flex; justify-content:space-between; width:100%;">
         <div style="font-weight: 800;">${r.name} · ${'★'.repeat(r.rating)}</div>
         <div style="font-size: 0.8rem; color: var(--gray);">${(r.created_at||'').slice(0,10)}</div>
      </div>
      <div style="font-size: 0.9rem;">${r.text}</div>`;
      
      const actions = ce('div', {style:'display:flex; gap:10px; margin-top:10px; width:100%;'});
      if(!r.approved) {
        const ok = ce('button', {class:'btn-adm btn-adm-save', style:'flex:1; padding:8px;'}); ok.textContent = 'Одобрить';
        ok.onclick = async () => { await PATCH('/reviews/'+r.id+'/approve'); renderAdminReviews(); };
        actions.appendChild(ok);
      }
      const del = ce('button', {class:'btn-adm btn-adm-danger', style:'flex:1; padding:8px;'}); del.textContent = 'Удалить';
      del.onclick = async () => { await DEL('/reviews/'+r.id); renderAdminReviews(); };
      actions.appendChild(del);
      
      row.appendChild(actions);
      list.appendChild(row);
    });
  } catch(e){ list.innerHTML = 'Ошибка загрузки отзывов'; }
}

// ── Admin Orders ─────────────────────────────────────────────────────
async function loadAdminOrders(){
  const list=$('adminOrdersContainer'); if(!list) return;
  list.innerHTML='<div class="adm-hint-text">Загрузка...</div>';
  const statusFilter = document.querySelector('.orders-filters .filter-btn.active')?.dataset.status || 'all';
  try {
    const orders = await GET('/orders?status='+(statusFilter==='all'?'':statusFilter));
    list.innerHTML='';
    if(!orders.length) { list.innerHTML = '<div class="adm-hint-text">Заказов пока нет</div>'; return; }
    orders.forEach(o => {
      const card = document.createElement('div'); card.className = 'adm-order-card';
      const items = (o.items||[]).map(i => `<div style="display:flex; justify-content:space-between; font-size:0.9rem;"><span>${i.name} × ${i.qty}</span><span>${i.price*i.qty} ₽</span></div>`).join('');
      
      card.innerHTML = `
        <div class="adm-order-header">
           <span class="adm-order-id">#${o.order_num}</span>
           <span class="adm-order-status" style="background: #f1f5f9; color: var(--dark);">${STATUS_LABELS[o.status]||o.status}</span>
        </div>
        <div style="margin-bottom: 12px; font-weight: 700;">👤 ${o.name} · ${o.phone}</div>
        <div style="margin-bottom: 12px; font-size: 0.85rem; color: var(--gray);">📍 ${o.address || 'Самовывоз'}</div>
        <div style="border-top: 1px dashed #e2e8f0; padding-top: 10px; margin-bottom: 10px;">${items}</div>
        <div style="font-weight: 800; font-size: 1.1rem; text-align: right; margin-bottom: 15px;">Итого: ${o.total} ₽</div>
        <div class="adm-btn-row">
           <select class="adm-input" style="flex:1;" onchange="updateOrderStatus(${o.id}, this.value)">
              ${Object.entries(STATUS_LABELS).map(([v,l]) => `<option value="${v}" ${v===o.status?'selected':''}>${l}</option>`).join('')}
           </select>
           <button class="btn-adm btn-adm-danger" onclick="deleteOrder(${o.id})" style="padding: 10px 15px;">🗑</button>
        </div>
      `;
      list.appendChild(card);
    });
  } catch(e){ list.innerHTML = 'Ошибка: ' + e.message; }
}

async function updateOrderStatus(id, status){
  try { await PATCH('/orders/'+id+'/status', {status}); showToast('✅ Статус обновлен'); loadAdminOrders(); }
  catch(e){ showToast(e.message); }
}

async function deleteOrder(id){
  if(!confirm('Удалить этот заказ навсегда?')) return;
  try { await DEL('/orders/'+id); showToast('🗑 Заказ удален'); loadAdminOrders(); }
  catch(e){ showToast(e.message); }
}

// Event delegation for order status filters
document.querySelector('.orders-filters')?.addEventListener('click', e => {
  const btn = e.target.closest('.filter-btn');
  if(btn) {
    document.querySelectorAll('.orders-filters .filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    loadAdminOrders();
  }
});

// ── Admin Users ─────────────────────────────────────────────────────
async function loadAdminUsers(){
  const list=$('adminUsersContainer'); if(!list) return;
  list.innerHTML='';
  try {
    const users = await GET('/admin/users');
    users.forEach(u => {
      const row = document.createElement('div'); row.className = 'adm-list-item';
      row.innerHTML = `
        <div class="adm-user-card">
           <div class="user-avatar-lg">${u.username.charAt(0).toUpperCase()}</div>
           <div>
              <div style="font-weight: 800;">${u.full_name || u.username}</div>
              <div style="font-size: 0.8rem; color: var(--gray);">${ROLE_LABELS[u.role]} · ${u.email||''}</div>
           </div>
        </div>
        <div class="adm-list-item-actions">
           <select class="adm-input" style="padding: 5px 10px; font-size: 0.8rem;" onchange="updateUserRole(${u.id}, this.value)">
              <option value="client" ${u.role==='client'?'selected':''}>Клиент</option>
              <option value="manager" ${u.role==='manager'?'selected':''}>Менеджер</option>
              <option value="admin" ${u.role==='admin'?'selected':''}>Админ</option>
           </select>
           <button class="btn-adm btn-adm-danger" onclick="deleteUser(${u.id})" style="padding: 6px 12px;">🗑</button>
        </div>
      `;
      list.appendChild(row);
    });
  } catch(e){ list.innerHTML = 'Ошибка: ' + e.message; }
}

async function updateUserRole(id, role){
  try { await PATCH('/admin/users/'+id+'/role', {role}); showToast('✅ Роль изменена'); loadAdminUsers(); }
  catch(e){ showToast(e.message); }
}

async function deleteUser(id){
  if(!confirm('Удалить пользователя?')) return;
  try { await DEL('/admin/users/'+id); showToast('🗑 Удален'); loadAdminUsers(); }
  catch(e){ showToast(e.message); }
}

async function confirmResetPassword(){
  const newPass=$('resetPassInput').value;
  if(newPass.length<8){ showToast('⚠ Минимум 8 символов'); return; }
  try {
    await PATCH('/admin/users/'+resetPassUserId+'/reset-password',{new_password:newPass});
    $('resetPassModal').style.display='none'; showToast('✅ Пароль сброшен');
  } catch(e){ showToast('❌ '+e.message); }
}

// ── Admin Settings ───────────────────────────────────────
$('settingsForm')?.addEventListener('submit', async e => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const body = {};
  fd.forEach((v, k) => {
    if(e.target.elements[k].type === 'checkbox') body[k] = e.target.elements[k].checked;
    else if(e.target.elements[k].type === 'number') body[k] = parseFloat(v) || 0;
    else body[k] = v;
  });
  
  // Add colors
  body.accent_color = $('primaryColorPick').value;

  try {
    await POST('/settings', body);
    state.settings = { ...state.settings, ...body };
    applySettings(state.settings);
    showToast('✅ Все настройки сохранены');
  } catch(err) { showToast('❌ ' + err.message); }
});


// ═══════════════════════════════════════════════════════════════════
// PANELS & MODALS
// ═══════════════════════════════════════════════════════════════════
function openCart(){ $('cartPanel').classList.add('open'); $('overlay').classList.add('show'); $('cartPanel').setAttribute('aria-hidden','false'); trapFocus($('cartPanel')); }
function closeCart(){ $('cartPanel').classList.remove('open'); if(!$('adminPanel')?.classList.contains('open')&&!$('clientPanel')?.classList.contains('open')) $('overlay').classList.remove('show'); $('cartPanel').setAttribute('aria-hidden','true'); }

function openModal(id){ $(id).classList.add('open'); $(id).setAttribute('aria-hidden','false'); trapFocus($(id)); }
function closeModal(id){ $(id).classList.remove('open'); $(id).setAttribute('aria-hidden','true'); }

function trapFocus(container){ const f=container.querySelectorAll('button,input,select,textarea,a[href],[tabindex]:not([tabindex="-1"])'); if(f.length) setTimeout(()=>f[0].focus(),50); }

document.querySelectorAll('.modal-wrap').forEach(wrap=>{
  wrap.addEventListener('click',e=>{ if(e.target===wrap){ wrap.classList.remove('open'); wrap.setAttribute('aria-hidden','true'); } });
});

// FIX: ESC closes only topmost modal, not all at once
document.addEventListener('keydown',e=>{
  if(e.key!=='Escape') return;
  if($('resetPassModal')?.style.display==='flex'){ $('resetPassModal').style.display='none'; return; }
  const modals=['checkoutModal','reviewModal','trackingModal','authModal'].map(id=>$(id)).filter(m=>m?.classList.contains('open'));
  if(modals.length){ const last=modals[modals.length-1]; last.classList.remove('open'); last.setAttribute('aria-hidden','true'); return; }
  if($('adminPanel')?.classList.contains('open')){ closeAdmin(); return; }
  if($('clientPanel')?.classList.contains('open')){ closeClientPanel(); return; }
  if($('cartPanel')?.classList.contains('open')) closeCart();
});

// ═══════════════════════════════════════════════════════════════════
// NAV / HAMBURGER
// ═══════════════════════════════════════════════════════════════════
$('hamburger').addEventListener('click',()=>{
  const open=$('navLinks').classList.toggle('open');
  $('hamburger').classList.toggle('open',open); $('hamburger').setAttribute('aria-expanded',open);
});
document.querySelectorAll('.nav-links a').forEach(a=>{
  a.addEventListener('click',()=>{ $('navLinks').classList.remove('open'); $('hamburger').classList.remove('open'); $('hamburger').setAttribute('aria-expanded','false'); });
});

// ═══════════════════════════════════════════════════════════════════
// SCROLL
// ═══════════════════════════════════════════════════════════════════
let ticking=false;
window.addEventListener('scroll',()=>{
  if(!ticking){ requestAnimationFrame(()=>{ $('nav').classList.toggle('scrolled',window.scrollY>40); $('backToTop').classList.toggle('show',window.scrollY>400); ticking=false; }); ticking=true; }
});
$('backToTop').addEventListener('click',()=>window.scrollTo({top:0,behavior:'smooth'}));

// ═══════════════════════════════════════════════════════════════════
// CONTACT FORM
// ═══════════════════════════════════════════════════════════════════
$('contactForm').addEventListener('submit',e=>{
  e.preventDefault(); let ok=true;
  const nameInp=e.target.querySelector('[name="name"]'); const phoneInp=e.target.querySelector('[name="phone"]');
  if(!nameInp.value.trim()){ markError(nameInp,'Введите имя'); ok=false; } else clearError(nameInp);
  if(!phoneInp.value.trim()){ markError(phoneInp,'Введите телефон'); ok=false; } else clearError(phoneInp);
  if(!ok) return;
  showToast('✅ Сообщение отправлено! Мы свяжемся с вами.'); e.target.reset();
});

// ═══════════════════════════════════════════════════════════════════
// PROMO BANNER COPY
// ═══════════════════════════════════════════════════════════════════
$('promoCodeDisplay').addEventListener('click',()=>{
  const code=$('promoCodeDisplay').textContent;
  if(navigator.clipboard) navigator.clipboard.writeText(code).then(()=>showToast('📋 Промокод '+code+' скопирован!'));
});

// ═══════════════════════════════════════════════════════════════════
// TOAST
// ═══════════════════════════════════════════════════════════════════
function showToast(msg){
  const wrap=$('toastWrap');
  const toast=document.createElement('div'); toast.className='toast'; toast.textContent=msg;
  wrap.appendChild(toast);
  setTimeout(()=>{ toast.classList.add('removing'); toast.addEventListener('animationend',()=>toast.remove(),{once:true}); },3000);
}

// ── Sticky Nav & Mobile Scroll ────────────────────────────────────
window.addEventListener('scroll',()=>{
  $('nav')?.classList.toggle('scrolled', window.scrollY > 50);
  $('backToTop')?.classList.toggle('show', window.scrollY > 400);
});

// ── Mobile Menu ───────────────────────────────────────────────────
function toggleMenu(){
  const nav=$('navLinks'); const ham=$('hamburger');
  if(!nav||!ham) return;
  const open=nav.classList.toggle('open');
  ham.classList.toggle('active');
  ham.setAttribute('aria-expanded',open);
  if(open) $('overlay').classList.add('show');
  else {
    if(!document.querySelector('.cart-panel.open') && !document.querySelector('.client-panel.open') && !document.querySelector('.admin-panel.open')) $('overlay').classList.remove('show');
    closeMobileSub();
  }
}
function toggleMobileSub(e){
  e?.preventDefault();
  const sub = $('mobileCatList');
  const parent = sub?.closest('.has-submenu');
  if(!sub || !parent) return;
  const isOpen = sub.classList.toggle('open');
  parent.classList.toggle('active', isOpen);
}
function closeMobileSub(){
  $('mobileCatList')?.classList.remove('open');
  document.querySelector('.has-submenu')?.classList.remove('active');
}
function closeMenu(){
  $('navLinks')?.classList.remove('open');
  $('hamburger')?.classList.remove('active');
  $('hamburger')?.setAttribute('aria-expanded','false');
  closeMobileSub();
  if(!document.querySelector('.cart-panel.open') && !document.querySelector('.client-panel.open') && !document.querySelector('.admin-panel.open')) $('overlay').classList.remove('show');
}
$('hamburger')?.addEventListener('click',toggleMenu);

// ═══════════════════════════════════════════════════════════════════
// EVENT LISTENERS
// ═══════════════════════════════════════════════════════════════════
$('cartBtn').addEventListener('click',openCart);
$('closeCart').addEventListener('click',closeCart);
$('adminCloseBtn')?.addEventListener('click', () => adminUI.close());
$('checkoutBtn').addEventListener('click',openCheckout);
$('adminLogout')?.addEventListener('click', doLogout);
$('overlay').addEventListener('click',()=>{ closeCart(); adminUI.close(); closeClientPanel(); closeMenu(); });

document.querySelector('.filter-btn[data-cat="all"]').addEventListener('click',function(){
  document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.cat-card').forEach(c=>c.classList.remove('active'));
  this.classList.add('active'); state.activeFilter='all'; renderMenu();
});

// ═══════════════════════════════════════════════════════════════════
// OFFLINE FALLBACK DATA
// ═══════════════════════════════════════════════════════════════════
function loadOfflineFallback(){
  state.categories=[{id:1,name:'Пицца',emoji:'🍕'},{id:2,name:'Бургеры',emoji:'🍔'},{id:3,name:'Суши',emoji:'🍣'},{id:4,name:'Паста',emoji:'🍝'},{id:5,name:'Салаты',emoji:'🥗'},{id:6,name:'Десерты',emoji:'🍰'}];
  state.menu=[
    {id:1,name:'Пицца Маргарита',description:'Томатный соус, моцарелла, свежий базилик',price:450,category:'Пицца',emoji:'🍕',photo_url:'',badge:'хит'},
    {id:2,name:'Пицца Пепперони',description:'Острая пепперони, томатный соус, сыр',price:520,category:'Пицца',emoji:'🍕',photo_url:'',badge:''},
    {id:3,name:'Пицца 4 сыра',description:'Моцарелла, пармезан, горгонзола, чеддер',price:590,category:'Пицца',emoji:'🍕',photo_url:'',badge:'новинка'},
    {id:4,name:'Чизбургер',description:'Говяжья котлета, чеддер, маринованный огурец',price:380,category:'Бургеры',emoji:'🍔',photo_url:'',badge:'хит'},
    {id:5,name:'Смоки Бургер',description:'Копчёная котлета, бекон, лук, BBQ соус',price:430,category:'Бургеры',emoji:'🍔',photo_url:'',badge:''},
    {id:6,name:'Гриль Бургер',description:'Говядина на гриле, авокадо, руккола',price:480,category:'Бургеры',emoji:'🍔',photo_url:'',badge:'новинка'},
    {id:7,name:'Сет Калифорния',description:'Краб, авокадо, огурец, икра тобико',price:680,category:'Суши',emoji:'🍣',photo_url:'',badge:'хит'},
    {id:8,name:'Лосось Ролл',description:'Нежный лосось, сливочный сыр, огурец',price:620,category:'Суши',emoji:'🍣',photo_url:'',badge:''},
    {id:9,name:'Карбонара',description:'Паста, бекон, яйцо, пармезан, сливки',price:490,category:'Паста',emoji:'🍝',photo_url:'',badge:''},
    {id:10,name:'Болоньезе',description:'Мясной соус, томаты, пармезан, базилик',price:460,category:'Паста',emoji:'🍝',photo_url:'',badge:'хит'},
    {id:11,name:'Греческий салат',description:'Фета, оливки, огурец, томаты, перец',price:320,category:'Салаты',emoji:'🥗',photo_url:'',badge:''},
    {id:12,name:'Тирамису',description:'Маскарпоне, савоярди, кофе, какао',price:290,category:'Десерты',emoji:'🍰',photo_url:'',badge:'новинка'},
  ];
  state.reviews=[
    {id:1,name:'Анна К.',rating:5,text:'Всё пришло горячим, упаковка отличная!',approved:1,created_at:'2025-05-12'},
    {id:2,name:'Дмитрий',rating:5,text:'Пицца Маргарита — лучшая в городе!',approved:1,created_at:'2025-05-08'},
    {id:3,name:'Мария С.',rating:4,text:'Отличное меню, большой выбор.',approved:1,created_at:'2025-05-02'},
  ];
  state.promos=[{id:1,code:'СЕЙЧАСТЬЕ',type:'percent',value:10,min_sum:0,description:'Скидка 10%',active:1,used_cnt:0}];
}

// ═══════════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════════
async function init(){
  try {
    const [cats,menu,reviews,settings]=await Promise.all([GET('/categories'),GET('/menu'),GET('/reviews'),GET('/settings')]);
    state.categories=cats; state.menu=menu;
    state.reviews=reviews; state.settings=settings;
    applySettings(settings);
  } catch(e){
    console.warn('API недоступен, офлайн-режим:', e.message);
    loadOfflineFallback();
  }
  renderCategories(); renderMenu(); renderHits(); renderReviews(); updateCartUI(); checkAuthStatus();
}

init();
