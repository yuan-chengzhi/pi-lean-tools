import Lean

namespace LeanToolsDemo

def demoValue : Nat := 1

theorem demo_add_zero (n : Nat) : n + 0 = n := by
  exact Nat.add_zero n

lemma demo_identity (p : Prop) : p -> p := by
  intro hp
  exact hp

end LeanToolsDemo
