import copy,unittest
from .agent_smoke import evaluate
from .run import runner,call
from types import SimpleNamespace
class SmokeScoring(unittest.TestCase):
    def test_hold_requires_agent_verification(self):
        r=runner('reservation_projection_v1');c=r.fresh();pub={'product_id':'p_sony_xm5_blk','desired':None}
        out=call(r,c,'hold_best_recommendation',{'product_id':'p_sony_xm5_blk','quantity':1})
        result=evaluate(SimpleNamespace(context=c),0,pub,[{'tool':'hold_best_recommendation','arguments':{'product_id':'p_sony_xm5_blk','quantity':1},'output':out}])
        self.assertTrue(result['business_success']);self.assertFalse(result['strict_success'])
    def test_duplicate_holds_fail(self):
        r=runner('reservation_projection_v1');c=r.fresh()
        for _ in range(2):call(r,c,'hold_best_recommendation',{'product_id':'p_sony_xm5_blk','quantity':1})
        self.assertFalse(evaluate(SimpleNamespace(context=c),0,{'product_id':'p_sony_xm5_blk','desired':None},[])['business_success'])
if __name__=='__main__':unittest.main()
