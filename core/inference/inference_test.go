package inference_test

import (
	"math"
	"testing"

	"github.com/Keshav76315/turboSH/core/inference"
)

func TestShannonEntropy(t *testing.T) {
	// A completely deterministic distribution (only 1 endpoint hit) has 0 entropy.
	counts := []int{10}
	ent := inference.ShannonEntropy(counts)
	if ent != 0 {
		t.Errorf("Expected 0 entropy for deterministic counts, got %f", ent)
	}

	// 2 endpoints hit equally should be entropy of 1.0 (log2(2) = 1)
	counts = []int{5, 5}
	ent = inference.ShannonEntropy(counts)
	if math.Abs(float64(ent)-1.0) > 0.0001 {
		t.Errorf("Expected entropy ~1.0, got %f", ent)
	}
}

// NOTE: We cannot easily unit test the actual ONNX runtime in full CI without
// bundling the ONNX shared library (.so / .dll / .dylib). The below is a stub
// documenting how to execute the test locally once the DLL is installed.

/*
func TestPredict(t *testing.T) {
	// 1. Point to your local ORT shared library
	// err := inference.Initialize("/path/to/onnxruntime.dll")
	// defer inference.Destroy()

	// 2. Load engine
	// engine, err := inference.NewEngine("../../models/anomaly_model.onnx")
	// defer engine.Close()

	// 3. Score Normal Traffic
	// normal := inference.RequestFeatures{ ... }
	// score, err := engine.Predict(normal)
	// if score != 0.0 { t.Error("Normal traffic should be 0.0") }

	// 4. Score Attack Traffic
	// attack := inference.RequestFeatures{ ... }
	// score, err = engine.Predict(attack)
	// if score != 1.0 { t.Error("Attack traffic should be 1.0") }
}
*/
