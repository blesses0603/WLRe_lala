"""Official organization donation rules; never infer or evaluate arbitrary Lua."""
from wlre.services.parser_diagnostics import diagnosed
from wlre.services.world.daily_task_1275 import Reader

TABLES=('UISellData_C','FormulaData_C','OrganizationFunctionData_C')


@diagnosed('guild-sell-v1')
def parse_sell(raw):
    r=Reader(raw);count=r.i32();rows={}
    if not 0<count<=10000:raise ValueError('UISell 筆數無效')
    for _ in range(count):
        row=dict(id=r.u16(),sell_kind=r.u8(),save_index=r.u8(),base_count=r.u8(),
                 base_kind=r.u8(),base_formula=r.u16(),second_kind=r.u8(),second_formula=r.u16(),
                 item_id=r.u16(),item_count=r.u8(),limit_kind=r.u8(),total_count=r.u8())
        row['texts']=[r.u32() for _ in range(6)];row['limit_flag']=r.u8()
        if not row['id'] or row['id'] in rows:raise ValueError('UISell 索引重複／無效')
        rows[row['id']]=row
    if r.pos!=len(raw):raise ValueError('UISell 格式變動')
    return rows


@diagnosed('guild-formulas-v1')
def parse_formulas(raw):
    r=Reader(raw);count=r.i32();rows={}
    if not 0<count<=65535:raise ValueError('公式筆數無效')
    for _ in range(count):
        index=r.u16();kind=r.u8();params=[r.u16() for _ in range(12)]
        if not index or index in rows:raise ValueError('公式索引重複／無效')
        rows[index]=dict(kind=kind,params=params)
    if r.pos!=len(raw):raise ValueError('公式格式變動')
    return rows


@diagnosed('guild-organization-v1')
def parse_organization(raw):
    r=Reader(raw);count=r.i32();rows={}
    if not 0<count<=255:raise ValueError('組織等級筆數無效')
    for _ in range(count):
        level=r.u8();develop=r.u32();limit=r.u8()
        awards=[dict(coin=r.u16(),materials=r.u16(),develop=r.u16()) for _ in range(3)]
        permissions=[r.u8() for _ in range(12)]
        if not level or level in rows or not limit:raise ValueError('組織等級／捐獻上限無效')
        rows[level]=dict(level=level,develop=develop,donate_limit=limit,awards=awards,permissions=permissions)
    if r.pos!=len(raw):raise ValueError('組織功能表格式變動')
    return rows


def quote(catalog,sell_id,counts,ready):
    row=catalog['sell'].get(sell_id)
    if sell_id not in (8,9,10) or not row:raise ValueError('沒有同版組織捐獻資料')
    if row['sell_kind']!=0:raise ValueError('不自動捐獻需扣物品的方案')
    if row['limit_flag'] or row['limit_kind'] and not row['save_index']:
        raise ValueError('捐獻方案有未核對的功能限制')
    index=row['save_index']
    if index and (not ready or str(index) not in counts):raise ValueError('等待伺服器消費次數同步')
    count=counts.get(str(index),0) if index else 0
    prefix='base_' if row['base_count']>count else 'second_'
    kind=row[prefix+'kind'];formula_id=row[prefix+'formula']
    if kind==5:price=0
    else:
        formula=catalog['formulas'].get(formula_id)
        if not formula or formula['kind']!=2:raise ValueError('捐獻價格公式未支援，停止消費')
        price=formula['params'][0]
    if kind not in (4,5):raise ValueError('自動捐獻只允許金幣／免費方案，不使用鑽石')
    if row['total_count'] and index and count>=row['total_count']:raise ValueError('捐獻消費次數已達上限')
    return dict(price=price,price_kind=kind,sell_id=sell_id,save_index=index,count=count,
                item_index=None if row['sell_kind']==0 else 0)


def load_verified_catalog(manifest,bundle_root,loader,root,identity):
    from wlre.services.world.resource_database import load_verified_tables
    parsed,sources=load_verified_tables(manifest,bundle_root,loader,root,identity,
                  {'guild_sell':('UISellData_C',parse_sell),'guild_formulas':('FormulaData_C',parse_formulas),
                   'guild_levels':('OrganizationFunctionData_C',parse_organization)})
    sell=parsed['guild_sell']
    if any(i not in sell for i in (8,9,10)):raise ValueError('組織捐獻方案缺少')
    return dict(sell=sell,formulas=parsed['guild_formulas'],levels=parsed['guild_levels'],sources=sources)
