//! The preparation stages, in ladder order.
//!
//! One module per stage, mirroring `evaluation/scripts/prepare_candidate.py`:
//! each stage is a pure `&str -> Stage` source transform whose edits carry
//! their evidence and whose abstentions are findings, never guesses.

pub(crate) mod arity;
pub(crate) mod coerce_word_returns;
pub(crate) mod declarations;
pub(crate) mod fallback_shape;
pub(crate) mod helpers;
pub(crate) mod lower_unknown_external_calls;
pub(crate) mod mutability;
pub(crate) mod packed_scalars;
pub(crate) mod param_types;
pub(crate) mod placeholders;
pub(crate) mod selfref;
pub(crate) mod send_guards;
pub(crate) mod slot_aliases;
pub(crate) mod storage_getters;
pub(crate) mod truthiness;
pub(crate) mod typed_packed_literals;
pub(crate) mod vars;
pub(crate) mod widen_packed_pair_returns;
pub(crate) mod wordify_address_mask;
