//go:build cgo

package inference

import (
	"fmt"
	"log"
	"path/filepath"

	ort "github.com/yalue/onnxruntime_go"
)

// Engine wraps the ONNX runtime session for executing the anomaly model.
type Engine struct {
	session     *ort.DynamicAdvancedSession
	modelLoaded bool
}

var SharedLibraryPath string

// Initialize sets up the ONNX runtime library. Requires the path to the
// ONNX Runtime Shared Library (.so, .dll, or .dylib).
func Initialize(sharedLibPath string) error {
	if ort.IsInitialized() {
		log.Printf("[inference] ONNX Environment already initialized (requested: %s, active: %s)", sharedLibPath, SharedLibraryPath)
		return nil
	}

	SharedLibraryPath = sharedLibPath
	ort.SetSharedLibraryPath(sharedLibPath)
	err := ort.InitializeEnvironment()
	if err != nil {
		return fmt.Errorf("failed to initialize ONNX environment: %w", err)
	}
	log.Printf("[inference] ONNX Runtime Environment initialized using %s", sharedLibPath)
	return nil
}

// Destroy cleans up the ONNX environment on application shutdown.
func Destroy() {
	ort.DestroyEnvironment()
	log.Println("[inference] ONNX Environment destroyed")
}

// NewEngine creates a new ML Inference Engine by loading a .onnx model file.
func NewEngine(modelPath string) (*Engine, error) {
	if !ort.IsInitialized() {
		return nil, fmt.Errorf("ONNX environment is not initialized. Call inference.Initialize() first")
	}

	absPath, err := filepath.Abs(modelPath)
	if err != nil {
		return nil, fmt.Errorf("invalid model path: %w", err)
	}

	// For Isolation Forest from skl2onnx, input is typically named "float_input"
	// and output is typically named "label" or "output_label".
	// We'll configure the session dynamically to discover types.

	inputNames := []string{"float_input"}
	outputNames := []string{"label"}

	// We expect the model to take a tensor of float32, and output a tensor of int64.
	// Since we are running dynamically, we don't bind static shapes permanently.
	session, err := ort.NewDynamicAdvancedSession(absPath, inputNames, outputNames, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to load session for model %s: %w", absPath, err)
	}

	log.Printf("[inference] Loaded ML model %s successfully", absPath)

	return &Engine{
		session:     session,
		modelLoaded: true,
	}, nil
}

// Close releases the session resources.
func (e *Engine) Close() {
	if e.session != nil {
		e.session.Destroy()
		e.session = nil
		e.modelLoaded = false
	}
}

// Predict takes structured request features, runs them through the Isolation Forest,
// and returns a normalized anomaly score (0.0 to 1.0).
func (e *Engine) Predict(features RequestFeatures) (float64, error) {
	if !e.modelLoaded {
		return 0, fmt.Errorf("model is not loaded")
	}

	inputData := features.ToArray()
	n := len(inputData)
	if n == 0 {
		return 0, fmt.Errorf("input features cannot be empty")
	}

	// Create a tensor for a single batch of shape (1, n)
	inputShape := ort.NewShape(1, int64(n))

	// Create input tensor wrapping our data
	inputTensor, err := ort.NewTensor(inputShape, inputData)
	if err != nil {
		return 0, fmt.Errorf("failed to create input tensor: %w", err)
	}
	defer inputTensor.Destroy()

	// The output of IsolationForest in skl2onnx is an array of Int64 (-1 or 1)
	outputData := make([]int64, 1)
	outputShape := ort.NewShape(1, 1)

	outputTensor, err := ort.NewTensor(outputShape, outputData)
	if err != nil {
		return 0, fmt.Errorf("failed to create output tensor: %w", err)
	}
	defer outputTensor.Destroy()

	// Execute Inference
	err = e.session.Run([]ort.ArbitraryTensor{inputTensor}, []ort.ArbitraryTensor{outputTensor})
	if err != nil {
		return 0, fmt.Errorf("inference run failed: %w", err)
	}

	// Extract the raw score and normalize it
	rawScore := outputTensor.GetData()[0]
	score := NormalizeScore(rawScore)

	return score, nil
}
