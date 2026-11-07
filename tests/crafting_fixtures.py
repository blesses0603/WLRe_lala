"""Synthetic recipes for UI/scheduling tests; no bundled game catalog dependency."""
def recipes():
    return {str(sid): {'item_id':sid,'tool_id':39001,'output':1,'seconds':10,
        'materials':[{'item_id':34144+i,'count':1} for i in range(5)],
        'design_id':0,'time_id':0,'limit_kind':0,'open_used':0}
        for sid in range(34026,34056)}
