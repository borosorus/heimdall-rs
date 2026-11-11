//! The preparation stages, in ladder order.
//!
//! One module per stage, mirroring `evaluation/scripts/prepare_candidate.py`:
//! each stage is a pure `&str -> Stage` source transform whose edits carry
//! their evidence and whose abstentions are findings, never guesses.

pub(crate) mod arity;
pub(crate) mod declarations;
pub(crate) mod fallback_shape;
pub(crate) mod helpers;
pub(crate) mod mutability;
pub(crate) mod packed_scalars;
pub(crate) mod param_types;
pub(crate) mod placeholders;
pub(crate) mod selfref;
pub(crate) mod send_guards;
pub(crate) mod slot_aliases;
pub(crate) mod storage_getters;
pub(crate) mod truthiness;
pub(crate) mod vars;
