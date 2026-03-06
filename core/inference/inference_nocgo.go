//go:build !cgo

package inference

import (
	"errors"
	"log"
)

// Engine is a stub for when CGO is disabled.
type Engine struct{}

// Initialize stubs the ONNX initialization.
func Initialize(sharedLibPath string) error {
	log.Println("[inference] Built without CGO. ONNX ML inference is disabled in this environment.")
	return errors.New("ONNX requires CGO support")
}

// Destroy stubs cleanup.
func Destroy() {}

// NewEngine stubs model loading.
func NewEngine(modelPath string) (*Engine, error) {
	return nil, errors.New("ONNX requires CGO support")
}

// Close is a stub.
func (e *Engine) Close() {}

// Predict is a stub.
func (e *Engine) Predict(features RequestFeatures) (float64, error) {
	return 0.0, errors.New("ONNX requires CGO support")
}
