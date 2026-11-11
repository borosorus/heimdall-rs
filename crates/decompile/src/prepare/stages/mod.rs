//! The preparation stages, in ladder order.
//!
//! One module per stage, mirroring `evaluation/scripts/prepare_candidate.py`:
//! each stage is a pure `&str -> Stage` source transform whose edits carry
//! their evidence and whose abstentions are findings, never guesses.

pub(crate) mod declarations;
pub(crate) mod helpers;
pub(crate) mod placeholders;
pub(crate) mod selfref;
pub(crate) mod vars;
