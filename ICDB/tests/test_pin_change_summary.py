import unittest
from qt_pin_changes import summarize_pin_changes

class TestPinChangeSummary(unittest.TestCase):
    def test_one_role_in_32_pins(self):
        old=[{'number':i,'name':f'P{i}','role':'Signal','description':''} for i in range(1,33)]
        new=[dict(p) for p in old]
        new[17]['role']='Power'
        summary=summarize_pin_changes(old,new)
        self.assertEqual(len(summary),2)
        self.assertIn('31 unchanged',summary[0])
        self.assertIn('Pin 18: role:', summary[1])
        self.assertNotIn('Pin 17:', '\n'.join(summary))
    def test_add_remove(self):
        old=[{'number':1,'name':'A','role':'Signal','description':''}]
        new=[['2','B','Signal','']]
        summary=summarize_pin_changes(old,new)
        self.assertIn('Pin 1: removed',summary[1])
        self.assertIn('Pin 2: added',summary[2])
    def test_unchanged(self):
        a=[{'number':'1','name':'A','role':'Signal','description':''}]
        self.assertEqual(summarize_pin_changes(a,[list(a[0].values())]),[])
    def test_order_changed(self):
        a=[{'number':i,'name':f'P{i}','role':'Signal','description':''} for i in (1,2,3)]
        self.assertIn('Pin order changed', summarize_pin_changes(a,[a[2],a[0],a[1]]))
if __name__=='__main__': unittest.main()
