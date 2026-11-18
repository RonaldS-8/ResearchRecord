import copy,unittest
from .adapter import runner
from extensions.execution_memory_058.run import InferenceContext

class ProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=runner('reservation_projection_v1');cls.n=runner('native')
    def call(self,r,ctx,tool,args):return r.ex.execute(tool,args,ctx,len(ctx.history)+1)
    def macro(self,r,ctx,q=1):return self.call(r,ctx,'hold_best_recommendation',{'product_id':'p_sony_xm5_blk','quantity':q,'user_id':'test_user','category':'electronics'})
    def stock(self,r,ctx,pid):return self.call(r,ctx,'get_stock_level',{'product_id':pid})
    def test_expansion_equivalence_bindings(self):
        for q in (1,2):
            a=InferenceContext();b=InferenceContext();out=self.macro(self.r,a,q);pid=out['product_id']
            rec=self.call(self.r,b,'get_recommendations',{'product_id':'p_sony_xm5_blk','user_id':'test_user','category':'electronics'})
            sel=self.call(self.r,b,'select_recommendation',{'similar_products':rec['similar_products'],'quantity':q})
            self.call(self.r,b,'hold_inventory',{'product_id':sel['product_id'],'quantity':q,'user_id':'test_user'})
            self.assertNotEqual(pid,'p_sony_xm5_blk');self.assertEqual(sel['product_id'],pid)
            self.assertEqual(self.stock(self.r,a,pid),self.stock(self.r,b,pid))
    def test_repeat_and_queries_and_mixing(self):
        c=InferenceContext();out=self.macro(self.r,c);pid=out['product_id'];initial=self.stock(self.r,InferenceContext(),pid)['stock']
        self.assertEqual(self.stock(self.r,c,pid)['stock'],initial-1)
        self.assertEqual(self.stock(self.r,c,pid)['stock'],initial-1)
        again=self.macro(self.r,c);self.assertEqual(again['reservation_id'],out['reservation_id'])
        self.call(self.r,c,'hold_inventory',{'product_id':pid,'quantity':2})
        self.assertEqual(self.stock(self.r,c,pid)['stock'],initial-4)
        self.assertEqual(sum(x.tool_name=='hold_inventory' for x in c.history),1)
    def test_native_unchanged_and_isolation(self):
        c=InferenceContext();out=self.macro(self.n,c);pid=out['product_id'];self.assertEqual(self.stock(self.n,c,pid)['stock'],self.stock(self.n,InferenceContext(),pid)['stock'])
        a=copy.deepcopy(c);b=copy.deepcopy(c);self.macro(self.r,a)
        self.assertNotEqual(self.stock(self.r,a,pid)['stock'],self.stock(self.r,b,pid)['stock'])
    def test_bad_and_unsupported_evidence(self):
        for tool,out in [('hold_best_recommendation',{'product_id':'x','quantity':1}),('checkout_best_recommendation',{'status':'confirmed'})]:
            c=InferenceContext();c.record(1,tool,{},out,'success');self.assertEqual(self.stock(self.r,c,'p_sony_xm5_slv')['verification'],'unknown')
    def test_failed_macro_no_effect(self):
        c=InferenceContext();c.record(1,'hold_best_recommendation',{}, {'error':'no stock'},'error')
        self.assertEqual(self.stock(self.r,c,'p_sony_xm5_slv'),self.stock(self.r,InferenceContext(),'p_sony_xm5_slv'))
if __name__=='__main__':unittest.main()
