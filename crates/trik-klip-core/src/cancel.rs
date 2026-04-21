// Shared cancel-signal plumbing for long-running pipeline stages.

use tokio::sync::watch;

pub type CancelRx = watch::Receiver<bool>;

/// Resolves when `rx` transitions to `true`. If `rx` is `None`, never resolves
/// — meant for use in `tokio::select!` to opt out of cancellation.
pub async fn wait_cancelled(rx: Option<&mut CancelRx>) {
    let Some(rx) = rx else {
        std::future::pending::<()>().await;
        return;
    };
    loop {
        if *rx.borrow() {
            return;
        }
        if rx.changed().await.is_err() {
            // Sender dropped — treat as never cancelled.
            std::future::pending::<()>().await;
            return;
        }
    }
}

/// Returns true if the cancel signal is currently set.
pub fn is_cancelled(rx: &CancelRx) -> bool {
    *rx.borrow()
}
