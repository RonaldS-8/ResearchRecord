"""ADR0034: query-only reservation projection; native plugins remain untouched."""
import copy
from dataclasses import replace
from types import SimpleNamespace
from extensions.execution_memory_058.run import Runner

class ProjectionExecutor:
    def __init__(self,native,mode='native'):
        if mode not in ('native','reservation_projection_v1'):raise ValueError(mode)
        self.native=native;self.mode=mode
    def execute(self,tool,args,context,step):
        if self.mode=='native' or tool!='get_stock_level':return self.native.execute(tool,args,context,step)
        projected=[];error=None
        for record in context.history:
            if record.tool_name in ('checkout_best_recommendation','build_recommended_invoice_request','generate_invoice_for_best_recommendation') and 'error' not in record.output:
                error='unsupported composite reservation';break
            if record.tool_name!='hold_best_recommendation' or 'error' in record.output:
                projected.append(record);continue
            out=record.output;details=out.get('reservation_details',{});q=out.get('quantity');pid=out.get('product_id')
            if (not isinstance(q,int) or isinstance(q,bool) or q<=0 or not pid or details.get('product_id')!=pid or details.get('quantity')!=q):
                error='incomplete or inconsistent reservation evidence';break
            projected.append(replace(record,tool_name='hold_inventory',output=copy.deepcopy(out)))
        args=self.native._coerce_types(tool,copy.deepcopy(args));validation=self.native._validate(tool,args)
        if validation:out={'error':'Validation failed','details':validation}
        elif error:out={'error':error,'verification':'unknown'}
        else:out=self.native.get_plugin(tool).execute(args,SimpleNamespace(history=projected))
        context.record(step,tool,args,out,'error' if 'error' in out else 'success')
        return out


def runner(mode):
    r=Runner();r.ex=ProjectionExecutor(r.ex,mode);return r
