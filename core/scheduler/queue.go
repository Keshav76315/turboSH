// Package scheduler implements request scheduling and concurrency control.
package scheduler

import (
	"container/heap"
	"sync"
	"time"
)

// Priority levels for request scheduling.
const (
	PriorityHigh   = 0
	PriorityNormal = 1
	PriorityLow    = 2
)

// Item represents a request waiting in the priority queue.
type Item struct {
	Priority  int       // Lower number = higher priority
	Timestamp time.Time // When the request was enqueued (for FIFO within same priority)
	Ready     chan struct{}
	index     int // Managed by heap.Interface
}

// PriorityQueue implements heap.Interface for request scheduling.
type PriorityQueue struct {
	items []*Item
	mu    sync.Mutex
}

// NewPriorityQueue creates a new empty priority queue.
func NewPriorityQueue() *PriorityQueue {
	pq := &PriorityQueue{
		items: make([]*Item, 0),
	}
	heap.Init(pq)
	return pq
}

// Len returns the number of items in the queue.
func (pq *PriorityQueue) Len() int {
	return len(pq.items)
}

// Less determines priority ordering.
// Lower priority number wins; ties broken by timestamp (FIFO).
func (pq *PriorityQueue) Less(i, j int) bool {
	if pq.items[i].Priority == pq.items[j].Priority {
		return pq.items[i].Timestamp.Before(pq.items[j].Timestamp)
	}
	return pq.items[i].Priority < pq.items[j].Priority
}

// Swap swaps two items in the queue.
func (pq *PriorityQueue) Swap(i, j int) {
	pq.items[i], pq.items[j] = pq.items[j], pq.items[i]
	pq.items[i].index = i
	pq.items[j].index = j
}

// Push adds an item to the queue (used by heap.Push).
func (pq *PriorityQueue) Push(x interface{}) {
	item := x.(*Item)
	item.index = len(pq.items)
	pq.items = append(pq.items, item)
}

// Pop removes and returns the highest-priority item (used by heap.Pop).
func (pq *PriorityQueue) Pop() interface{} {
	old := pq.items
	n := len(old)
	item := old[n-1]
	old[n-1] = nil // avoid memory leak
	item.index = -1
	pq.items = old[:n-1]
	return item
}

// Enqueue adds a request to the queue with the given priority.
// Returns the Item so the caller can wait on its Ready channel.
func (pq *PriorityQueue) Enqueue(priority int) *Item {
	pq.mu.Lock()
	defer pq.mu.Unlock()

	item := &Item{
		Priority:  priority,
		Timestamp: time.Now(),
		Ready:     make(chan struct{}),
	}
	heap.Push(pq, item)
	return item
}

// Dequeue removes and returns the highest-priority item.
// Returns nil if the queue is empty.
func (pq *PriorityQueue) Dequeue() *Item {
	pq.mu.Lock()
	defer pq.mu.Unlock()

	if pq.Len() == 0 {
		return nil
	}
	item := heap.Pop(pq).(*Item)
	close(item.Ready)
	return item
}

// Size returns the current number of items in the queue (thread-safe).
func (pq *PriorityQueue) Size() int {
	pq.mu.Lock()
	defer pq.mu.Unlock()
	return pq.Len()
}
