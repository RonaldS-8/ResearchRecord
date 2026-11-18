import unittest
from .run import obligation,contract_check,PublicLoader
from evaluation.core.judge import JudgeSystem

class Checks(unittest.TestCase):
    def test_execution_success_is_not_business_success(self):
        t={'success':True,'outputs':[{'similar_products':[{'id':'silver','stock':2}]},{'product_id':'black','available_stock':2}]}
        self.assertEqual(obligation('selection',{'quantity':1},t)['receipt'],'reject')
    def test_order_receipt_does_not_certify_state(self):
        t={'success':True,'outputs':[{'product_id':'silver','quantity':1}]}
        self.assertEqual(obligation('order',{'product_id':'black','quantity':1},t)['state'],'unknown')
    def test_missing_invoice_evidence_rejects(self):
        t={'success':True,'outputs':[{'status':'generated'}]}
        self.assertEqual(obligation('invoice',{'email':'x','amount':10,'payment_gateway':'stripe'},t)['receipt'],'reject')
    def test_forward_dependency_rejected(self):
        self.assertFalse(contract_check([('select_recommendation',{'similar_products':'$1.similar_products'})],{},PublicLoader()))
    def test_native_judge_ignores_business_values(self):
        # Isolated evaluator fixture, never exposed to runner or memory.
        task={'complexity':'C3','perturbation_mode':'P0','valid_paths':[{'path_id':'fixture','tools':['confirm_order']}]}
        trace={'messages':[{'role':'assistant','type':'tool_call','tool_call':{'name':'confirm_order','id':'x','arguments':{'product_id':'WRONG'}}},{'role':'tool','tool_call_id':'x','name':'confirm_order','content':{'product_id':'WRONG','status':'confirmed'}}]}
        self.assertTrue(JudgeSystem().judge(task,trace)['pass'])
if __name__=='__main__':unittest.main()
